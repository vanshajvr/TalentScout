import uuid
import secrets
import hashlib
from datetime import datetime, timedelta

from fastapi import HTTPException, Header, Depends
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Recruiter, RecruiterSession

VALID_TOKENS: dict[str, tuple[str, datetime]] = {}
TOKEN_TTL = timedelta(hours=12)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return digest.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


def hash_token(token: str) -> str:
    # The token itself already has 256 bits of entropy (secrets.token_urlsafe(32)), so a plain
    # unsalted SHA-256 is sufficient here — unlike password hashing, there's no low-entropy
    # secret to protect against brute force, just a need to avoid storing it in reusable form.
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(
    recruiter: Recruiter, db: SQLASession, ip: str | None = None, user_agent: str | None = None
) -> str:
    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = (str(recruiter.id), datetime.utcnow() + TOKEN_TTL)

    db.add(RecruiterSession(
        recruiter_id=recruiter.id, org_id=recruiter.org_id, email_attempted=recruiter.email,
        success=True, ip=ip, user_agent=user_agent, token_hash=hash_token(token),
        started_at=datetime.utcnow(),
    ))
    db.commit()
    return token


def record_failed_login(
    db: SQLASession, email: str, ip: str | None, user_agent: str | None,
    recruiter: Recruiter | None = None,
) -> None:
    # Linking recruiter_id/org_id when the email matches a real account (even though the
    # password was wrong) distinguishes "guessing against a known employee" from "hitting a
    # made-up address" — the former is the stronger signal for spotting a targeted attack.
    db.add(RecruiterSession(
        recruiter_id=recruiter.id if recruiter else None,
        org_id=recruiter.org_id if recruiter else None,
        email_attempted=email[:255],
        success=False, ip=ip, user_agent=user_agent, token_hash=None,
        started_at=datetime.utcnow(),
    ))
    db.commit()


def close_session(db: SQLASession, token: str, reason: str, at: datetime | None = None) -> None:
    row = db.query(RecruiterSession).filter(RecruiterSession.token_hash == hash_token(token)).first()
    if row is not None and row.ended_at is None:
        row.ended_at = at or datetime.utcnow()
        row.end_reason = reason
        db.commit()


def logout(db: SQLASession, token: str) -> None:
    VALID_TOKENS.pop(token, None)
    close_session(db, token, "logout")


def _resolve_token(token: str, db: SQLASession) -> str:
    entry = VALID_TOKENS.get(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    recruiter_id, expires_at = entry
    if datetime.utcnow() > expires_at:
        del VALID_TOKENS[token]
        close_session(db, token, "expired", at=expires_at)
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    return recruiter_id


def require_recruiter(authorization: str = Header(None), db: SQLASession = Depends(get_db)) -> Recruiter:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    recruiter_id = _resolve_token(token, db)
    recruiter = db.get(Recruiter, uuid.UUID(recruiter_id))
    if recruiter is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return recruiter


def require_admin(recruiter: Recruiter = Depends(require_recruiter)) -> Recruiter:
    if recruiter.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return recruiter