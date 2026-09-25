import csv
import io
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, GeneratedQuestion, Recruiter, SessionLog, InviteToken, Organization, MCQAssessment, MCQAnswer, MCQQuestion, RecruiterSession

from utils.validators import is_valid_email
from utils.auth import (
    hash_password, verify_password, issue_token, require_recruiter, _resolve_token,
    record_failed_login, logout as auth_logout,
)

from utils.schemas import AuthResponse

router = APIRouter(prefix="/recruiter")

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=8)
    invite_code: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

class DeleteCandidatesRequest(BaseModel):
    candidate_ids: list[str]

@router.get("/org")
def get_my_org(db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter)):
    org = db.get(Organization, recruiter.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"org_name": org.name, "org_slug": org.slug}

@router.post("/signup", response_model=AuthResponse)
def recruiter_signup(body: SignupRequest, request: Request, db: SQLASession = Depends(get_db)):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    token_row = db.query(InviteToken).filter(InviteToken.code == body.invite_code).with_for_update().first()
    if token_row is None:
        raise HTTPException(status_code=403, detail="Invalid invite code")
    if token_row.used_at is not None:
        raise HTTPException(status_code=403, detail="This invite code has already been used")
    if token_row.revoked_at is not None:
        raise HTTPException(status_code=403, detail="This invite code has been revoked")
    if token_row.expires_at is not None and datetime.utcnow() > token_row.expires_at:
        raise HTTPException(status_code=403, detail="This invite code has expired")

    if not is_valid_email(body.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    existing = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    

    password_hash = hash_password(body.password)
    recruiter = Recruiter(
        name=body.name, email=body.email, password_hash=password_hash,
        org_id=token_row.org_id, role="recruiter",
    )
    db.add(recruiter)
    db.flush()  # assigns recruiter.id without committing — the row lock on token_row
                # must survive until both the recruiter row and the token's used_* fields
                # are written together, or a second concurrent request could still slip
                # through between two separate commits.

    token_row.used_by = recruiter.id
    token_row.used_by_name = recruiter.name
    token_row.used_ip = ip
    token_row.used_user_agent = user_agent
    token_row.used_at = datetime.utcnow()
    db.commit()
    db.refresh(recruiter)

    token = issue_token(recruiter, db, ip=ip, user_agent=user_agent)
    return AuthResponse(token=token, name=recruiter.name)

LOGIN_LOCKOUT_THRESHOLD = 5
LOGIN_LOCKOUT_WINDOW_MINUTES = 15


@router.post("/login", response_model=AuthResponse)
def recruiter_login(body: LoginRequest, request: Request, db: SQLASession = Depends(get_db)):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    window_start = datetime.utcnow() - timedelta(minutes=LOGIN_LOCKOUT_WINDOW_MINUTES)
    recent_failures = db.query(RecruiterSession).filter(
        RecruiterSession.email_attempted == body.email,
        RecruiterSession.success.is_(False),
        RecruiterSession.started_at >= window_start,
    ).count()
    if recent_failures >= LOGIN_LOCKOUT_THRESHOLD:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Please try again in {LOGIN_LOCKOUT_WINDOW_MINUTES} minutes.",
        )

    recruiter = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if recruiter is None:
        record_failed_login(db, body.email, ip, user_agent, recruiter=None)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    is_valid, upgraded_hash = verify_password(body.password, recruiter.password_hash, recruiter.password_salt)
    if not is_valid:
        record_failed_login(db, body.email, ip, user_agent, recruiter=recruiter)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if upgraded_hash is not None:
        # A legacy PBKDF2 account just verified correctly — migrate it to argon2 now,
        # since we have the real password in hand and will never get another chance
        # to do this without asking the user to reset it.
        recruiter.password_hash = upgraded_hash
        recruiter.password_salt = None
        db.commit()

    token = issue_token(recruiter, db, ip=ip, user_agent=user_agent)
    return AuthResponse(token=token, name=recruiter.name)


@router.post("/logout")
def recruiter_logout(authorization: str = Header(None), db: SQLASession = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    auth_logout(db, token)
    return {"logged_out": True}


@router.get("/me")
def get_me(authorization: str = Header(None), db: SQLASession = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    recruiter_id = _resolve_token(token, db)
    recruiter = db.get(Recruiter, uuid.UUID(recruiter_id))
    if recruiter is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return {"id": str(recruiter.id), "name": recruiter.name, "email": recruiter.email, "role": recruiter.role}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    is_valid, _ = verify_password(body.current_password, recruiter.password_hash, recruiter.password_salt)
    if not is_valid:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    recruiter.password_hash = hash_password(body.new_password)
    recruiter.password_salt = None  # the new hash is always argon2, no legacy salt needed

    # Close every active session for this account, including the one making this
    # request — a password change is often prompted by a suspicion the account was
    # compromised, and leaving old tokens valid would defeat the point. The
    # frontend handles this by redirecting to login right after a successful change.
    db.query(RecruiterSession).filter(
        RecruiterSession.recruiter_id == recruiter.id,
        RecruiterSession.ended_at.is_(None),
    ).update({"ended_at": datetime.utcnow(), "end_reason": "password_changed"}, synchronize_session=False)

    db.commit()
    return {"status": "ok"}

ABANDONED_AFTER_HOURS = 48


def _sweep_stale_sessions(db: SQLASession, org_id) -> None:
    """Lazily corrects any in_progress session that's gone quiet for 48+ hours to
    "abandoned" — a candidate who just closes the tab (never types an exit keyword,
    never finishes) would otherwise sit as "in_progress" forever, inflating that stat
    indefinitely. Called at the top of the recruiter-facing read endpoints, so the DB
    self-corrects for real whenever someone actually looks, rather than needing a
    separate background job. A flat 48h-since-started_at check is accurate enough
    here — this screening flow takes at most 20-40 minutes even fully engaged, so the
    gap between "started" and "actually went quiet" is dwarfed by the 48h window."""
    threshold = datetime.utcnow() - timedelta(hours=ABANDONED_AFTER_HOURS)
    db.query(SessionModel).filter(
        SessionModel.status == "in_progress",
        SessionModel.started_at < threshold,
        SessionModel.candidate_id.in_(
            db.query(Candidate.id).filter(Candidate.org_id == org_id)
        ),
    ).update({"status": "abandoned"}, synchronize_session=False)
    db.commit()


def _candidate_query(db, org_id, role, tech, min_experience, status):
    q = db.query(Candidate, SessionModel).join(SessionModel, SessionModel.candidate_id == Candidate.id)
    q = q.filter(Candidate.org_id == org_id)
    if role:
        q = q.filter(Candidate.role.ilike(f"%{role}%"))
    if min_experience is not None:
        q = q.filter(Candidate.experience >= min_experience)
    if status:
        q = q.filter(SessionModel.status == status)
    results = q.all()
    if tech:
        results = [(c, s) for c, s in results if c.tech_stack and any(tech.lower() in t.lower() for t in c.tech_stack)]
    return results


@router.get("/candidates")
def list_candidates(
    role: str | None = None, tech: str | None = None,
    min_experience: float | None = None, status: str | None = None,
    db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    _sweep_stale_sessions(db, recruiter.org_id)
    rows = _candidate_query(db, recruiter.org_id, role, tech, min_experience, status)
    return [
        {
            "id": str(c.id), "session_id": str(s.id), "name": c.name, "email": c.email,
            "phone": c.phone, "location": c.location, "experience": c.experience, "role": c.role,
            "tech_stack": c.tech_stack, "resume_filename": c.resume_filename,
            "status": s.status, "current_step": s.current_step,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, s in rows
    ]


@router.get("/overview")
def overview(db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter)):
    _sweep_stale_sessions(db, recruiter.org_id)
    total = db.query(Candidate).filter(Candidate.org_id == recruiter.org_id).count()
    in_progress = (
        db.query(SessionModel).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, SessionModel.status == "in_progress").count()
    )
    completed = (
        db.query(SessionModel).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, SessionModel.status == "completed").count()
    )
    abandoned = (
        db.query(SessionModel).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, SessionModel.status == "abandoned").count()
    )
    experiences = [
    c.experience for c in db.query(Candidate)
    .filter(Candidate.org_id == recruiter.org_id, Candidate.experience.isnot(None)).all()
    if c.experience is not None
    ]   
    avg_experience = round(sum(experiences) / len(experiences), 1) if experiences else None
    return {
        "total_candidates": total, "in_progress": in_progress, "completed": completed,
        "abandoned": abandoned, "avg_experience": avg_experience,
    }


@router.get("/candidates/{candidate_id}/questions")
def candidate_questions(
    candidate_id: str, db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid candidate_id")
    candidate_row = db.get(Candidate, cid)
    if candidate_row is None or candidate_row.org_id != recruiter.org_id:
        raise HTTPException(status_code=404, detail="Candidate not found")

    session_row = db.query(SessionModel).filter(SessionModel.candidate_id == cid).order_by(SessionModel.started_at.desc()).first()
    if session_row is None:
        return {"assessment_type": "none", "legacy_questions": []}

    assessment = db.query(MCQAssessment).filter(MCQAssessment.session_id == session_row.id).first()

    if assessment is not None:
        answers = db.query(MCQAnswer).filter(MCQAnswer.assessment_id == assessment.id).order_by(MCQAnswer.question_index).all()

        technical_answers = [a for a in answers if a.question_type == "technical"]
        technical_score = sum(1 for a in technical_answers if a.is_correct)
        technical_total = len(technical_answers)
        final_difficulty_tier = technical_answers[-1].difficulty_tier if technical_answers else None

        duration_minutes = None
        if assessment.completed_at is not None:
            duration_minutes = round((assessment.completed_at - assessment.started_at).total_seconds() / 60)

        # Correct-option lookup for technical questions, joined via pool_question_id.
        pool_ids = [a.pool_question_id for a in technical_answers if a.pool_question_id is not None]
        correct_by_pool_id = {
            q.id: q.correct_option_id for q in db.query(MCQQuestion).filter(MCQQuestion.id.in_(pool_ids)).all()
        } if pool_ids else {}

        question_payloads = []
        for a in answers:
            payload = {
                "question_index": a.question_index,
                "question_type": a.question_type,
                "question_text": a.question_text,
                "options": a.options_snapshot,
                "selected_option_id": a.selected_option_id,
                "text_response": a.text_response,
                "time_taken_seconds": a.time_taken_seconds,
            }
            if a.question_type == "technical":
                payload["is_correct"] = a.is_correct
                payload["difficulty_tier"] = a.difficulty_tier
                payload["correct_option_id"] = correct_by_pool_id.get(a.pool_question_id) if a.pool_question_id else None
            question_payloads.append(payload)

        return {
            "assessment_type": "mcq",
            "mcq": {
                "status": assessment.status,
                "duration_minutes": duration_minutes,
                "technical_score": technical_score,
                "technical_total": technical_total,
                "final_difficulty_tier": final_difficulty_tier,
                "tab_switch_count": assessment.tab_switch_count,
                "fullscreen_exit_count": assessment.fullscreen_exit_count,
                "questions": question_payloads,
            },
        }

    # No MCQ assessment for this candidate's session — fall back to the legacy
    # conversational-flow question data.
    legacy_questions = db.query(GeneratedQuestion).filter(GeneratedQuestion.session_id == session_row.id).all()
    return {
        "assessment_type": "legacy",
        "legacy_questions": [
            {"technology": q.technology, "question_text": q.question_text, "answer_text": q.answer_text, "difficulty_tier": q.difficulty_tier}
            for q in legacy_questions
        ],
    }


def _csv_safe(value) -> str:
    """Neutralizes CSV formula injection: a cell value starting with =, +, -, or @
    gets interpreted as a formula by Excel/Google Sheets when the export is opened.
    Every field here traces back to a candidate-supplied resume, so all of it is
    attacker-controlled. Prefixing with a single quote forces literal-text display."""
    text = str(value) if value is not None else ""
    if text and text[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text


@router.get("/candidates/export")
def export_candidates(
    role: str | None = None, tech: str | None = None,
    min_experience: float | None = None, status: str | None = None,
    db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    rows = _candidate_query(db, recruiter.org_id, role, tech, min_experience, status)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "Email", "Phone", "Location", "Experience", "Role", "Tech Stack", "Status", "Step", "Resume", "Applied At"])
    for c, s in rows:
        writer.writerow([
            _csv_safe(c.name), _csv_safe(c.email), _csv_safe(c.phone), _csv_safe(c.location),
            c.experience, _csv_safe(c.role),
            _csv_safe(", ".join(c.tech_stack) if c.tech_stack else ""),
            s.status, s.current_step, _csv_safe(c.resume_filename or ""),
            c.created_at.isoformat() if c.created_at else "",
        ])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=candidates.csv"})


@router.post("/candidates/delete")
def delete_candidates(
    body: DeleteCandidatesRequest, db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    deleted = 0
    for cid_str in body.candidate_ids:
        try:
            cid = uuid.UUID(cid_str)
        except ValueError:
            continue
        candidate_row = db.get(Candidate, cid)
        if candidate_row is None or candidate_row.org_id != recruiter.org_id:
            continue
        # Sessions, messages, generated questions, session logs, and any MCQ
        # assessment/answers all cascade-delete at the DB level (see
        # migrations/migrate_cascade_deletes.py) — no need to hand-delete each table here anymore.
        if candidate_row.resume_path:
            try:
                if os.path.exists(candidate_row.resume_path):
                    os.remove(candidate_row.resume_path)
            except OSError:
                pass  # best-effort cleanup — don't block the actual deletion over this
        db.delete(candidate_row)
        deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.get("/candidates/{candidate_id}/logs")
def candidate_logs(
    candidate_id: str, db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):  
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid candidate_id")
    candidate_row = db.get(Candidate, cid)
    if candidate_row is None or candidate_row.org_id != recruiter.org_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    session_row = db.query(SessionModel).filter(SessionModel.candidate_id == cid).first()
    if session_row is None:
        return []
    logs = db.query(SessionLog).filter(SessionLog.session_id == session_row.id).order_by(SessionLog.timestamp).all()
    return [{"event_type": l.event_type, "detail": l.detail, "timestamp": l.timestamp.isoformat()} for l in logs]


@router.get("/candidates/{candidate_id}/resume")
def download_resume(
    candidate_id: str, db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid candidate_id")
    candidate_row = db.get(Candidate, cid)
    if candidate_row is None or candidate_row.org_id != recruiter.org_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not candidate_row.resume_path or not os.path.exists(candidate_row.resume_path):
        raise HTTPException(status_code=404, detail="No resume on file for this candidate")
    return FileResponse(
        candidate_row.resume_path,
        filename=candidate_row.resume_filename or "resume",
        media_type="application/octet-stream",
    )