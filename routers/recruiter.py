import csv
import io
import os
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, GeneratedQuestion

router = APIRouter(prefix="/recruiter")

RECRUITER_PASSWORD = os.environ.get("RECRUITER_PASSWORD", "changeme")
VALID_TOKENS: set[str] = set()


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
def recruiter_login(body: LoginRequest):
    if body.password != RECRUITER_PASSWORD:
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = secrets.token_urlsafe(32)
    VALID_TOKENS.add(token)
    return LoginResponse(token=token)


def require_recruiter(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    if token not in VALID_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid or expired session — please log in again")


def _candidate_query(db, role, tech, min_experience, status):
    q = db.query(Candidate, SessionModel).join(SessionModel, SessionModel.candidate_id == Candidate.id)
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
    role: str | None = None,
    tech: str | None = None,
    min_experience: float | None = None,
    status: str | None = None,
    db: SQLASession = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    rows = _candidate_query(db, role, tech, min_experience, status)
    return [
        {
            "id": str(c.id), "session_id": str(s.id), "name": c.name, "email": c.email,
            "email_verified": c.email_verified, "phone": c.phone, "phone_verified": c.phone_verified,
            "location": c.location, "experience": c.experience, "role": c.role,
            "tech_stack": c.tech_stack, "resume_filename": c.resume_filename,
            "status": s.status, "current_step": s.current_step,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, s in rows
    ]

@router.get("/overview")
def overview(db: SQLASession = Depends(get_db), _: None = Depends(require_recruiter)):
    total = db.query(Candidate).count()
    in_progress = db.query(SessionModel).filter(SessionModel.status == "in_progress").count()
    completed = db.query(SessionModel).filter(SessionModel.status == "completed").count()
    experiences: list[float] = [
        c.experience
        for c in db.query(Candidate).filter(Candidate.experience.isnot(None)).all()
        if c.experience is not None
    ]
    avg_experience = round(sum(experiences) / len(experiences), 1) if experiences else None
    return {
        "total_candidates": total,
        "in_progress": in_progress,
        "completed": completed,
        "avg_experience": avg_experience,
    }


@router.get("/candidates/{candidate_id}/questions")
def candidate_questions(
    candidate_id: str,
    db: SQLASession = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        cid = uuid.UUID(candidate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid candidate_id")

    session_row = db.query(SessionModel).filter(SessionModel.candidate_id == cid).first()
    if session_row is None:
        return []

    questions = (
        db.query(GeneratedQuestion)
        .filter(GeneratedQuestion.session_id == session_row.id)
        .all()
    )
    return [
        {
            "technology": q.technology,
            "question_text": q.question_text,
            "answer_text": q.answer_text,
            "difficulty_tier": q.difficulty_tier,
        }
        for q in questions
    ]


@router.get("/candidates/export")
def export_candidates(
    role: str | None = None,
    tech: str | None = None,
    min_experience: float | None = None,
    status: str | None = None,
    db: SQLASession = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    rows = _candidate_query(db, role, tech, min_experience, status)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Name", "Email", "Email Verified", "Phone", "Phone Verified",
        "Location", "Experience", "Role", "Tech Stack", "Status", "Step", "Resume", "Applied At",
    ])
    for c, s in rows:
        writer.writerow([
            c.name, c.email, c.email_verified, c.phone, c.phone_verified,
            c.location, c.experience, c.role,
            ", ".join(c.tech_stack) if c.tech_stack else "",
            s.status, s.current_step, c.resume_filename or "",
            c.created_at.isoformat() if c.created_at else "",
        ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=candidates.csv"},
    )