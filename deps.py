import uuid
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session as SQLASession

from db.models import Candidate, CandidateSession


def get_candidate_or_404(db: SQLASession, candidate_id: uuid.UUID) -> Candidate:
    row = db.get(Candidate, candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


def record_candidate_activity(db: SQLASession, session_row: CandidateSession) -> None:
    """Called on every candidate-side request. Stamps last_activity_at, and reopens a
    session the inactivity sweep marked abandoned (it never reached "end") — a candidate
    who comes back and finishes should end up "completed", not stuck as abandoned.
    Sessions abandoned via an exit keyword are at "end" and stay abandoned."""
    session_row.last_activity_at = datetime.utcnow()
    if session_row.status == "abandoned" and session_row.current_step != "end":
        session_row.status = "in_progress"
    db.commit()


def get_session_or_404(db: SQLASession, session_id: uuid.UUID) -> CandidateSession:
    row = db.get(CandidateSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row