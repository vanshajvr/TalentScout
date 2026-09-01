import uuid
import secrets
import hashlib
from datetime import datetime, timedelta

from fastapi import HTTPException, Header, Depends
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Recruiter

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


def issue_token(recruiter_id: str) -> str:
    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = (recruiter_id, datetime.utcnow() + TOKEN_TTL)
    return token


def _resolve_token(token: str) -> str:
    entry = VALID_TOKENS.get(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    recruiter_id, expires_at = entry
    if datetime.utcnow() > expires_at:
        del VALID_TOKENS[token]
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    return recruiter_id


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