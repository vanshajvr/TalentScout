import uuid
import secrets
import hashlib
from datetime import datetime, timedelta

from fastapi import HTTPException, Header, Depends
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Recruiter, RecruiterSession

TOKEN_TTL = timedelta(hours=12)


from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

_argon2_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Argon2's hash string embeds its own salt and cost parameters — no separate
    salt column needed for any account created from here on."""
    return _argon2_hasher.hash(password)


def verify_password(password: str, password_hash: str, password_salt: str | None = None) -> tuple[bool, str | None]:
    """
    Returns (is_valid, upgraded_hash). upgraded_hash is non-None only when a legacy
    PBKDF2 account (from before the argon2 switch) just verified correctly — callers
    should persist it as the account's new password_hash (and clear password_salt),
    migrating that account to argon2 the moment it next logs in successfully, with
    no separate mass-reset ever needed.
    """
    if password_hash.startswith("$argon2"):
        try:
            _argon2_hasher.verify(password_hash, password)
            return True, None
        except (VerifyMismatchError, InvalidHash):
            return False, None

    # Legacy PBKDF2 hash — needs the salt that was stored alongside it.
    if password_salt is None:
        return False, None
    legacy_digest = hashlib.pbkdf2_hmac("sha256", password.encode(), password_salt.encode(), 100_000).hex()
    if secrets.compare_digest(legacy_digest, password_hash):
        return True, hash_password(password)
    return False, None


def hash_token(token: str) -> str:
    # The token itself already has 256 bits of entropy (secrets.token_urlsafe(32)), so a plain
    # unsalted SHA-256 is sufficient here — unlike password hashing, there's no low-entropy
    # secret to protect against brute force, just a need to avoid storing it in reusable form.
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(
    recruiter: Recruiter, db: SQLASession, ip: str | None = None, user_agent: str | None = None
) -> str:
    token = secrets.token_urlsafe(32)

    db.add(RecruiterSession(
        recruiter_id=recruiter.id, org_id=recruiter.org_id, email_attempted=recruiter.email,
        success=True, ip=ip, user_agent=user_agent, token_hash=hash_token(token),
        expires_at=datetime.utcnow() + TOKEN_TTL, started_at=datetime.utcnow(),
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
        success=False, ip=ip, user_agent=user_agent, token_hash=None, expires_at=None,
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
    close_session(db, token, "logout")


def _resolve_token(token: str, db: SQLASession) -> str:
    """RecruiterSession is now the sole source of truth for token validity — no
    in-memory dict, so this survives restarts and works correctly across multiple
    worker processes."""
    row = db.query(RecruiterSession).filter(RecruiterSession.token_hash == hash_token(token)).first()
    if row is None or row.ended_at is not None or row.expires_at is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if datetime.utcnow() > row.expires_at:
        close_session(db, token, "expired", at=row.expires_at)
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    if row.recruiter_id is None:
        # The recruiter account behind this token was deleted after the token was
        # issued (recruiter_id goes NULL via ON DELETE SET NULL) — nothing to
        # authenticate as anymore, even though the token itself hasn't "expired".
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return str(row.recruiter_id)


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