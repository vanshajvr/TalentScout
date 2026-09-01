import csv
import io
import secrets
import hashlib
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion, Recruiter, SessionLog, InviteToken

from utils.validators import is_valid_email

router = APIRouter(prefix="/recruiter")

VALID_TOKENS: dict[str, tuple[str, datetime]] = {}  # token -> (recruiter_id, expires_at)
TOKEN_TTL = timedelta(hours=12)

def _resolve_token(token: str) -> str:
    entry = VALID_TOKENS.get(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    recruiter_id, expires_at = entry
    if datetime.utcnow() > expires_at:
        del VALID_TOKENS[token]
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    return recruiter_id


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
    invite_code: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    name: str
class DeleteCandidatesRequest(BaseModel):
    candidate_ids: list[str]


@router.post("/signup", response_model=AuthResponse)
def recruiter_signup(body: SignupRequest, db: SQLASession = Depends(get_db)):
    token_row = (
        db.query(InviteToken)
        .filter(InviteToken.code == body.invite_code, InviteToken.used_by.is_(None))
        .first()
    )
    if token_row is None:
        raise HTTPException(status_code=403, detail="Invalid or already-used invite code")
    
    if not is_valid_email(body.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    existing = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    

    password_hash, salt = _hash_password(body.password)
    recruiter = Recruiter(
        name=body.name, email=body.email, password_hash=password_hash,
        password_salt=salt, org_id=token_row.org_id, role="recruiter",
    )
    db.add(recruiter)
    db.commit()
    db.refresh(recruiter)

    token_row.used_by = recruiter.id
    token_row.used_at = datetime.now()
    db.commit()

    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = (str(recruiter.id), datetime.utcnow() + TOKEN_TTL)
    return AuthResponse(token=token, name=recruiter.name)

@router.post("/login", response_model=AuthResponse)
def recruiter_login(body: LoginRequest, db: SQLASession = Depends(get_db)):
    recruiter = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if recruiter is None or not _verify_password(body.password, recruiter.password_salt, recruiter.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = (str(recruiter.id), datetime.utcnow() + TOKEN_TTL)
    return AuthResponse(token=token, name=recruiter.name)


@router.get("/me")
def get_me(authorization: str = Header(None), db: SQLASession = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    recruiter_id = _resolve_token(token)
    recruiter = db.get(Recruiter, uuid.UUID(recruiter_id))
    if recruiter is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return {"name": recruiter.name, "email": recruiter.email, "role": recruiter.role}

def require_recruiter(authorization: str = Header(None), db: SQLASession = Depends(get_db)) -> Recruiter:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    recruiter_id = _resolve_token(token)
    recruiter = db.get(Recruiter, uuid.UUID(recruiter_id))
    if recruiter is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return recruiter

def require_admin(recruiter: Recruiter = Depends(require_recruiter)) -> Recruiter:
    if recruiter.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return recruiter

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
    session_row = db.query(SessionModel).filter(SessionModel.candidate_id == cid).first()
    if session_row is None:
        return []
    questions = db.query(GeneratedQuestion).filter(GeneratedQuestion.session_id == session_row.id).all()
    return [
        {"technology": q.technology, "question_text": q.question_text, "answer_text": q.answer_text, "difficulty_tier": q.difficulty_tier}
        for q in questions
    ]


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
        session_ids = [s.id for s in db.query(SessionModel).filter(SessionModel.candidate_id == cid).all()]
        if session_ids:
            db.query(GeneratedQuestion).filter(GeneratedQuestion.session_id.in_(session_ids)).delete(synchronize_session=False)
            db.query(Message).filter(Message.session_id.in_(session_ids)).delete(synchronize_session=False)
            db.query(SessionModel).filter(SessionModel.candidate_id == cid).delete(synchronize_session=False)
        db.delete(candidate_row)
        deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.get("/candidates/{candidate_id}/logs")
def candidate_logs(
    candidate_id: str, db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    cid = uuid.UUID(candidate_id)
    candidate_row = db.get(Candidate, cid)
    if candidate_row is None or candidate_row.org_id != recruiter.org_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    session_row = db.query(SessionModel).filter(SessionModel.candidate_id == cid).first()
    if session_row is None:
        return []
    logs = db.query(SessionLog).filter(SessionLog.session_id == session_row.id).order_by(SessionLog.timestamp).all()
    return [{"event_type": l.event_type, "detail": l.detail, "timestamp": l.timestamp.isoformat()} for l in logs]