import csv
import io
import os
import secrets
import hashlib
import uuid

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion, Recruiter

router = APIRouter(prefix="/recruiter")

VALID_TOKENS: dict[str, str] = {}  # token -> recruiter_id


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return digest.hex(), salt


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest, _ = _hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    name: str


@router.post("/signup", response_model=AuthResponse)
def recruiter_signup(body: SignupRequest, db: SQLASession = Depends(get_db)):
    existing = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    password_hash, salt = _hash_password(body.password)
    recruiter = Recruiter(name=body.name, email=body.email, password_hash=password_hash, password_salt=salt)
    db.add(recruiter)
    db.commit()
    db.refresh(recruiter)

    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = str(recruiter.id)
    return AuthResponse(token=token, name=recruiter.name)


@router.post("/login", response_model=AuthResponse)
def recruiter_login(body: LoginRequest, db: SQLASession = Depends(get_db)):
    recruiter = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if recruiter is None or not _verify_password(body.password, recruiter.password_salt, recruiter.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = str(recruiter.id)
    return AuthResponse(token=token, name=recruiter.name)


@router.get("/me")
def get_me(authorization: str = Header(None), db: SQLASession = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    recruiter_id = VALID_TOKENS.get(token)
    if not recruiter_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    recruiter = db.get(Recruiter, uuid.UUID(recruiter_id))
    if recruiter is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return {"name": recruiter.name, "email": recruiter.email}


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


class DeleteCandidatesRequest(BaseModel):
    candidate_ids: list[str]


@router.post("/candidates/delete")
def delete_candidates(
    body: DeleteCandidatesRequest,
    db: SQLASession = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    deleted = 0
    for cid_str in body.candidate_ids:
        try:
            cid = uuid.UUID(cid_str)
        except ValueError:
            continue

        session_ids = [
            s.id for s in db.query(SessionModel).filter(SessionModel.candidate_id == cid).all()
        ]
        if session_ids:
            db.query(GeneratedQuestion).filter(GeneratedQuestion.session_id.in_(session_ids)).delete(synchronize_session=False)
            db.query(Message).filter(Message.session_id.in_(session_ids)).delete(synchronize_session=False)
            db.query(SessionModel).filter(SessionModel.candidate_id == cid).delete(synchronize_session=False)

        candidate_row = db.get(Candidate, cid)
        if candidate_row is not None:
            db.delete(candidate_row)
            deleted += 1

    db.commit()
    return {"deleted": deleted}