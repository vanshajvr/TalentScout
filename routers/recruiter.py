import csv
import io
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, CandidateSession, GeneratedQuestion, Recruiter, SessionLog, InviteToken, Organization, MCQAssessment, MCQAnswer, MCQQuestion, RecruiterSession, JobOpening
from utils.validators import is_valid_email
from utils.auth import (
    hash_password, verify_password, issue_token, require_recruiter, _resolve_token,
    record_failed_login, logout as auth_logout,
)

from utils.schemas import AuthResponse
from utils.judge import RUBRIC_DIMENSIONS, overall, validate_scores
from routers.mcq import judge_and_store

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
    """Marks in_progress sessions with no candidate activity for 48+ hours as
    "abandoned" — a candidate who just closes the tab never types an exit keyword or
    finishes, and would otherwise count as "in progress" forever. Runs at the top of
    the recruiter-facing reads, so the data is corrected whenever someone looks,
    without a separate background job.

    Measured from the last activity, not from when the session started: candidates
    can resume (conversation state is persisted), so a session started three days ago
    that the candidate is working in right now is not abandoned. If an abandoned
    candidate does come back, deps.record_candidate_activity reopens the session."""
    threshold = datetime.utcnow() - timedelta(hours=ABANDONED_AFTER_HOURS)
    db.query(CandidateSession).filter(
        CandidateSession.status == "in_progress",
        func.coalesce(CandidateSession.last_activity_at, CandidateSession.started_at) < threshold,
        CandidateSession.candidate_id.in_(
            db.query(Candidate.id).filter(Candidate.org_id == org_id)
        ),
    ).update({"status": "abandoned"}, synchronize_session=False)
    db.commit()


def _candidate_query(db, org_id, role, tech, min_experience, status, job_id=None):
    q = db.query(Candidate, CandidateSession).join(CandidateSession, CandidateSession.candidate_id == Candidate.id)
    q = q.filter(Candidate.org_id == org_id)
    if job_id == "none":
        q = q.filter(Candidate.job_id.is_(None))
    elif job_id:
        try:
            q = q.filter(Candidate.job_id == uuid.UUID(job_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job_id")
        # Within a single job, the useful default is a ranking — best fit first,
        # unscored (resume not yet confirmed) last.
        q = q.order_by(Candidate.fit_score.desc().nullslast(), Candidate.created_at.desc())
    if role:
        q = q.filter(Candidate.role.ilike(f"%{role}%"))
    if min_experience is not None:
        q = q.filter(Candidate.experience >= min_experience)
    if status:
        q = q.filter(CandidateSession.status == status)
    results = q.all()
    if tech:
        results = [(c, s) for c, s in results if c.tech_stack and any(tech.lower() in t.lower() for t in c.tech_stack)]
    return results


def _job_titles(db, org_id) -> dict:
    return dict(db.query(JobOpening.id, JobOpening.title).filter(JobOpening.org_id == org_id).all())


@router.get("/candidates")
def list_candidates(
    role: str | None = None, tech: str | None = None,
    min_experience: float | None = None, status: str | None = None,
    job_id: str | None = None,
    db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    _sweep_stale_sessions(db, recruiter.org_id)
    rows = _candidate_query(db, recruiter.org_id, role, tech, min_experience, status, job_id)
    job_titles = _job_titles(db, recruiter.org_id)
    return [
        {
            "id": str(c.id), "session_id": str(s.id), "name": c.name, "email": c.email,
            "phone": c.phone, "location": c.location, "experience": c.experience, "role": c.role,
            "tech_stack": c.tech_stack, "resume_filename": c.resume_filename,
            "status": s.status, "current_step": s.current_step,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "job_id": str(c.job_id) if c.job_id else None,
            "job_title": job_titles.get(c.job_id),
            "fit_score": c.fit_score, "fit_summary": c.fit_summary, "fit_details": c.fit_details,
        }
        for c, s in rows
    ]


@router.get("/overview")
def overview(db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter)):
    _sweep_stale_sessions(db, recruiter.org_id)
    total = db.query(Candidate).filter(Candidate.org_id == recruiter.org_id).count()
    in_progress = (
        db.query(CandidateSession).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, CandidateSession.status == "in_progress").count()
    )
    completed = (
        db.query(CandidateSession).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, CandidateSession.status == "completed").count()
    )
    abandoned = (
        db.query(CandidateSession).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, CandidateSession.status == "abandoned").count()
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

    session_row = db.query(CandidateSession).filter(CandidateSession.candidate_id == cid).order_by(CandidateSession.started_at.desc()).first()
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
            elif a.question_type == "open_text":
                payload["judge"] = _judge_payload(a)
            question_payloads.append(payload)

        open_text_overalls = [
            p["judge"]["overall"] for p in question_payloads
            if p["question_type"] == "open_text" and p["judge"]["overall"] is not None
        ]

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
                "open_text_avg": round(sum(open_text_overalls) / len(open_text_overalls), 1) if open_text_overalls else None,
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


def _judge_payload(a: MCQAnswer) -> dict:
    effective = a.override_scores or a.judge_scores
    return {
        "status": (
            "overridden" if a.override_scores else
            "graded" if a.judge_scores else
            "failed" if a.judge_error else
            "pending" if a.answered_at else "unanswered"
        ),
        "scores": effective,
        "overall": overall(effective),
        "ai_scores": a.judge_scores,  # kept visible after an override, for comparison
        "rationale": a.judge_rationale,
        "manipulation_attempt": bool(a.judge_manipulation),
        "model": a.judge_model,
        "dimensions": list(RUBRIC_DIMENSIONS),
    }


def _org_candidate_assessment_or_404(db: SQLASession, candidate_id: str, org_id):
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid candidate_id")
    candidate_row = db.get(Candidate, cid)
    if candidate_row is None or candidate_row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    session_row = db.query(CandidateSession).filter(CandidateSession.candidate_id == cid).order_by(CandidateSession.started_at.desc()).first()
    assessment = db.query(MCQAssessment).filter(MCQAssessment.session_id == session_row.id).first() if session_row else None
    if assessment is None:
        raise HTTPException(status_code=404, detail="No assessment for this candidate")
    return candidate_row, assessment


@router.post("/candidates/{candidate_id}/judge")
def judge_candidate_answers(
    candidate_id: str, force: bool = False,
    db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter),
):
    """Grades any open-text answers the background judge missed (LLM outage, or answers
    submitted before this feature existed). force=true re-grades all of them, e.g.
    after a prompt change. Overrides are left untouched either way."""
    candidate_row, assessment = _org_candidate_assessment_or_404(db, candidate_id, recruiter.org_id)
    answers = db.query(MCQAnswer).filter(
        MCQAnswer.assessment_id == assessment.id,
        MCQAnswer.question_type == "open_text",
        MCQAnswer.answered_at.isnot(None),
    ).all()
    judged = failed = 0
    for a in answers:
        if a.judge_scores is not None and not force:
            continue
        if judge_and_store(db, a, candidate_row):
            judged += 1
        else:
            failed += 1
    db.commit()
    return {"judged": judged, "failed": failed}


class OverrideScoresRequest(BaseModel):
    scores: dict | None  # {relevance, specificity, clarity}: 1-5, or null to clear the override


@router.put("/candidates/{candidate_id}/answers/{question_index}/override")
def override_answer_scores(
    candidate_id: str, question_index: int, body: OverrideScoresRequest,
    db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter),
):
    _, assessment = _org_candidate_assessment_or_404(db, candidate_id, recruiter.org_id)
    answer = db.query(MCQAnswer).filter(
        MCQAnswer.assessment_id == assessment.id, MCQAnswer.question_index == question_index,
    ).first()
    if answer is None or answer.question_type != "open_text":
        raise HTTPException(status_code=404, detail="Open-text answer not found")

    if body.scores is None:
        answer.override_scores = None
        answer.override_by = None
        answer.override_at = None
    else:
        try:
            answer.override_scores = validate_scores(body.scores)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Scores must be whole numbers 1-5 for {', '.join(RUBRIC_DIMENSIONS)}: {e}")
        answer.override_by = recruiter.id
        answer.override_at = datetime.utcnow()
    db.commit()
    return _judge_payload(answer)


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
    job_id: str | None = None,
    db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    rows = _candidate_query(db, recruiter.org_id, role, tech, min_experience, status, job_id)
    job_titles = _job_titles(db, recruiter.org_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Name", "Email", "Phone", "Location", "Experience", "Role", "Tech Stack", "Status", "Step", "Resume", "Applied At",
        "Job", "Fit Score", "Fit Summary",
    ])
    for c, s in rows:
        writer.writerow([
            _csv_safe(c.name), _csv_safe(c.email), _csv_safe(c.phone), _csv_safe(c.location),
            c.experience, _csv_safe(c.role),
            _csv_safe(", ".join(c.tech_stack) if c.tech_stack else ""),
            s.status, s.current_step, _csv_safe(c.resume_filename or ""),
            c.created_at.isoformat() if c.created_at else "",
            # Job titles are recruiter-entered and fit summaries embed JD skill names —
            # less hostile than resume fields, but the same spreadsheet opens them.
            _csv_safe(job_titles.get(c.job_id, "")), c.fit_score if c.fit_score is not None else "",
            _csv_safe(c.fit_summary or ""),
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
    session_row = db.query(CandidateSession).filter(CandidateSession.candidate_id == cid).first()
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