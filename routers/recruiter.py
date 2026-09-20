import csv
import io
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

import db
from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion, Recruiter, SessionLog, InviteToken, Organization, MCQAssessment, MCQAnswer, MCQQuestion

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
    password: str
    invite_code: str


class LoginRequest(BaseModel):
    email: str
    password: str

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

    token_row = db.query(InviteToken).filter(InviteToken.code == body.invite_code).first()
    if token_row is None:
        raise HTTPException(status_code=403, detail="Invalid invite code")
    if token_row.used_by is not None:
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
    

    password_hash, salt = hash_password(body.password)
    recruiter = Recruiter(
        name=body.name, email=body.email, password_hash=password_hash,
        password_salt=salt, org_id=token_row.org_id, role="recruiter",
    )
    db.add(recruiter)
    db.commit()
    db.refresh(recruiter)

    token_row.used_by = recruiter.id
    token_row.used_by_name = recruiter.name
    token_row.used_ip = ip
    token_row.used_user_agent = user_agent
    token_row.used_at = datetime.now()
    db.commit()

    token = issue_token(recruiter, db, ip=ip, user_agent=user_agent)
    return AuthResponse(token=token, name=recruiter.name)

@router.post("/login", response_model=AuthResponse)
def recruiter_login(body: LoginRequest, request: Request, db: SQLASession = Depends(get_db)):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    recruiter = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if recruiter is None or not verify_password(body.password, recruiter.password_salt, recruiter.password_hash):
        record_failed_login(db, body.email, ip, user_agent, recruiter=recruiter)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

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
    return {"name": recruiter.name, "email": recruiter.email, "role": recruiter.role}

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
    total = db.query(Candidate).filter(Candidate.org_id == recruiter.org_id).count()
    in_progress = (
        db.query(SessionModel).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, SessionModel.status == "in_progress").count()
    )
    completed = (
        db.query(SessionModel).join(Candidate)
        .filter(Candidate.org_id == recruiter.org_id, SessionModel.status == "completed").count()
    )
    experiences = [
    c.experience for c in db.query(Candidate)
    .filter(Candidate.org_id == recruiter.org_id, Candidate.experience.isnot(None)).all()
    if c.experience is not None
    ]   
    avg_experience = round(sum(experiences) / len(experiences), 1) if experiences else None
    return {"total_candidates": total, "in_progress": in_progress, "completed": completed, "avg_experience": avg_experience}


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
            c.name, c.email, c.phone, c.location, c.experience, c.role,
            ", ".join(c.tech_stack) if c.tech_stack else "",
            s.status, s.current_step, c.resume_filename or "",
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
        # migrate_cascade_deletes.py) — no need to hand-delete each table here anymore.
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