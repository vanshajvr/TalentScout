import uuid
from fastapi import HTTPException
from sqlalchemy.orm import Session as SQLASession

from db.models import Candidate, Session as SessionModel


def get_candidate_or_404(db: SQLASession, candidate_id: uuid.UUID) -> Candidate:
    row = db.get(Candidate, candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


def get_session_or_404(db: SQLASession, session_id: uuid.UUID) -> SessionModel:
    row = db.get(SessionModel, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row