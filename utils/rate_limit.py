from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session as SQLASession

from db.models import RateLimitEvent


def check_rate_limit(db: SQLASession, key: str, max_requests: int, window_minutes: int) -> None:
    """Raises 429 if `key` (e.g. "start_session:<ip>") has made >= max_requests within
    the last window_minutes; otherwise records this request.

    Backed by Postgres rather than process memory, so limits hold across restarts,
    deploys and multiple workers. A transaction-scoped advisory lock on the key
    serializes concurrent requests for the same key — without it, a burst of parallel
    requests could all read "under the limit" before any of them recorded itself.
    Commits its own work, so call it before the endpoint does anything else.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    window_start = datetime.utcnow() - timedelta(minutes=window_minutes)
    # Expired rows for this key are dead weight; clearing them here keeps the table
    # bounded by (active keys x max_requests) with no separate cleanup job.
    db.query(RateLimitEvent).filter(
        RateLimitEvent.key == key, RateLimitEvent.created_at < window_start,
    ).delete(synchronize_session=False)

    recent = db.query(func.count(RateLimitEvent.id)).filter(RateLimitEvent.key == key).scalar()
    if recent >= max_requests:
        db.commit()  # keep the cleanup, release the lock
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    db.add(RateLimitEvent(key=key))
    db.commit()
