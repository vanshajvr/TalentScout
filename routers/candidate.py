import uuid
import os
import logging
from datetime import datetime

import pdfplumber
from docx import Document as DocxDocument
import json

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion, SessionLog, Organization
from conversation import ConversationState, handle_user_input, get_bot_message
from llm.groq_llm import GroqLLM
from utils.constants import BEHAVIORAL_QUESTION_TEMPLATES, MCQ_SEEDED_TECHNOLOGIES
from utils.validators import is_valid_email, is_valid_phone, is_valid_experience
from utils.rate_limit import check_rate_limit
from deps import get_candidate_or_404, get_session_or_404

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB — generous for a resume, rejects egregious uploads
MAX_RESUME_PDF_PAGES = 20  # any real resume is 1-3 pages; a page cap bounds extraction cost/time

RESUME_FILE_SIGNATURES = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",  # docx is a zip archive under the hood
}

llm = GroqLLM()
ACTIVE_SESSIONS: dict[str, ConversationState] = {}

class StartSessionResponse(BaseModel):
    session_id: str
    message: str


class MessageRequest(BaseModel):
    text: str
    pasted: bool = False


class MessageResponse(BaseModel):
    messages: list[str]
    step: str
    candidate: dict
    extracted: dict | None = None
    duplicate_email_choice: bool = False  # True when confirm_resume_data found an
                                            # abandoned prior attempt under this email
                                            # and is waiting on the candidate to choose
                                            # rather than treating it as a hard block

class ConfirmResumeRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    replace_duplicate: bool = False  # candidate's answer to the duplicate_email_choice prompt
    phone: str | None = Field(default=None, max_length=20)
    location: str | None = Field(default=None, max_length=120)
    experience: str | None = Field(default=None, max_length=20)
    role: str | None = Field(default=None, max_length=120)
    tech_stack: list[str] | None = Field(default=None, max_length=50)
    education: str | None = Field(default=None, max_length=255)
    linkedin: str | None = Field(default=None, max_length=255)
    github: str | None = Field(default=None, max_length=255)

def _extract_resume_text(file_path: str, ext: str) -> str:
    if ext == ".pdf":
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages[:MAX_RESUME_PDF_PAGES]:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                for link in getattr(page, "hyperlinks", []):
                    uri = link.get("uri", "")
                    if uri:
                        text_parts.append(f"[link: {uri}]")
        return "\n".join(text_parts)
    elif ext == ".docx":
        doc = DocxDocument(file_path)
        return "\n".join(p.text for p in doc.paragraphs)
    return ""

def _extract_resume_fields(resume_text: str, db: SQLASession, session_uuid: uuid.UUID) -> dict:
    if not resume_text.strip():
        return {}
    prompt_template = _load_prompt("prompts/resume_extraction_prompt.txt")
    prompt = prompt_template.format(
        resume_text=resume_text[:6000],
        canonical_technologies=", ".join(MCQ_SEEDED_TECHNOLOGIES),
    )
    try:
        raw = llm.generate(prompt, temperature=0).strip()
        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "", 1).strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("Resume extraction failed: %s", e)
        _log_event(db, session_uuid, "llm_fallback", f"Resume extraction failed: {e}")
        return {}
    
def _load_prompt(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def _sync_candidate_row(db: SQLASession, candidate_id: uuid.UUID, state: ConversationState) -> None:
    row = get_candidate_or_404(db, candidate_id)
    c = state.candidate
    row.name = c.name or None
    row.email = c.email or None
    row.education = c.education or None
    row.phone = c.phone or None
    row.location = c.location or None
    if c.experience and is_valid_experience(c.experience):
        row.experience = float(c.experience.replace("+", ""))
    else:
        row.experience = None
    row.role = c.role or None
    row.tech_stack = c.tech_stack or None
    row.linkedin_url = c.linkedin or None
    row.github_url = c.github or None
    db.commit()


def _difficulty_tier(experience) -> str:
    if experience is None:
        return "unknown"
    try:
        # experience can arrive as a string (e.g. "3+", from in-memory extraction data)
        # or as a genuine float (e.g. from the Candidate.experience DB column) — handle both.
        val = float(experience.replace("+", "")) if isinstance(experience, str) else float(experience)
    except (ValueError, TypeError):
        return "unknown"
    if val < 1:
        return "fundamentals"
    if val <= 3:
        return "applied"
    return "advanced"

def _log_event(db: SQLASession, session_uuid: uuid.UUID, event_type: str, detail: str):
    db.add(SessionLog(session_id=session_uuid, event_type=event_type, detail=detail))
    db.commit()

def _mark_step(db: SQLASession, session_uuid: uuid.UUID, session_row: SessionModel, new_step: str, exited_early: bool = False):
    """Advances session_row.current_step, logging the transition, and — if the new step
    is the final one — marks the session completed (or abandoned, if this "end" was
    reached via an exit keyword rather than a genuine finish)."""
    if session_row.current_step != new_step:
        _log_event(db, session_uuid, "step_transition", f"{session_row.current_step} -> {new_step}")
    session_row.current_step = new_step
    if new_step == "end" and session_row.status not in ("completed", "abandoned"):
        session_row.status = "abandoned" if exited_early else "completed"
        session_row.completed_at = datetime.utcnow()  # "session ended" timestamp either way — used for duration math regardless of how it ended
    db.commit()
        

@router.post("/sessions", response_model=StartSessionResponse)
def start_session(request: Request, org: str = "default", db: SQLASession = Depends(get_db)):
    ip = request.client.host if request.client else None
    check_rate_limit(f"start_session:{ip or 'unknown'}", max_requests=10, window_minutes=60)

    org_row = db.query(Organization).filter(Organization.slug == org).first()
    if org_row is None:
        raise HTTPException(status_code=404, detail="Unknown organization")

    candidate_row = Candidate(org_id=org_row.id)
    db.add(candidate_row)
    db.flush()

    session_row = SessionModel(candidate_id=candidate_row.id, current_step="greeting")
    db.add(session_row)
    db.commit()
    db.refresh(session_row)

    state = ConversationState()
    session_id = str(session_row.id)
    ACTIVE_SESSIONS[session_id] = state

    greeting = get_bot_message(state)
    db.add(Message(session_id=session_row.id, role="assistant", content=greeting))
    db.commit()

    return StartSessionResponse(session_id=session_id, message=greeting)

@router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
def post_message(session_id: str, body: MessageRequest, db: SQLASession = Depends(get_db)):
    state = ACTIVE_SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    session_row = get_session_or_404(db, session_uuid)

    db.add(Message(session_id=session_uuid, role="user", content=body.text, is_pasted=body.pasted))

    result = handle_user_input(state, body.text)
    state = result.state

    ACTIVE_SESSIONS[session_id] = state

    for msg in result.bot_messages:
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))

    _mark_step(db, session_uuid, session_row, state.step, exited_early=result.exited_early)

    _sync_candidate_row(db, session_row.candidate_id, state)


    bot_messages = list(result.bot_messages)
    ACTIVE_SESSIONS[session_id] = state

    return MessageResponse(
        messages=bot_messages,
        step=state.step,
        candidate=vars(state.candidate),
    )

@router.post("/sessions/{session_id}/resume")
def upload_resume(session_id: str, file: UploadFile = File(...), db: SQLASession = Depends(get_db)):
    state = ACTIVE_SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if state.step != "upload_resume":
        raise HTTPException(status_code=400, detail="Not expecting a resume upload right now")

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    allowed = {".pdf", ".docx"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Only PDF or DOCX files are accepted")

    content = file.file.read(MAX_RESUME_SIZE_BYTES + 1)
    if len(content) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume file is too large (10 MB max)")

    expected_signature = RESUME_FILE_SIGNATURES[ext]
    if not content.startswith(expected_signature):
        raise HTTPException(status_code=400, detail="File content doesn't match its extension")

    safe_name = f"{session_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(content)

    session_row = get_session_or_404(db, session_uuid)
    candidate_row = get_candidate_or_404(db, session_row.candidate_id)
    candidate_row.resume_filename = file.filename
    candidate_row.resume_path = dest_path
    db.commit()

    resume_text = _extract_resume_text(dest_path, ext)
    extracted = _extract_resume_fields(resume_text, db, session_uuid)
    candidate_row.resume_text = resume_text
    state.pending_resume_data = extracted
    if not extracted:
        _log_event(db, session_uuid, "error", "Resume extraction returned empty result")

    state.step = "confirm_resume_data"
    ACTIVE_SESSIONS[session_id] = state

    summary_lines = []
    if extracted.get("email") is not None: summary_lines.append(f"Email: {extracted['email']}")
    if extracted.get("phone") is not None: summary_lines.append(f"Phone: {extracted['phone']}")
    if extracted.get("location") is not None: summary_lines.append(f"Location: {extracted['location']}")
    if extracted.get("experience") is not None: summary_lines.append(f"Experience: {extracted['experience']} years")
    if extracted.get("role") is not None: summary_lines.append(f"Role: {extracted['role']}")
    if extracted.get("tech_stack"): summary_lines.append(f"Tech stack: {', '.join(extracted['tech_stack'])}")
    if extracted.get("education"): summary_lines.append(f"Education: {extracted['education']}")
    if extracted.get("linkedin"): summary_lines.append(f"LinkedIn: {extracted['linkedin']}")
    if extracted.get("github"): summary_lines.append(f"GitHub: {extracted['github']}")

    if summary_lines:
        bot_reply = (
            "Here's what I found on your resume:\n\n" + "\n".join(summary_lines) +
            "\n\nEdit anything below, then confirm."
        )
    else:
        bot_reply = "I couldn't extract much from that resume — please fill in your details below."

    db.add(Message(session_id=session_uuid, role="user", content=f"[uploaded resume: {file.filename}]"))
    db.add(Message(session_id=session_uuid, role="assistant", content=bot_reply))
    _mark_step(db, session_uuid, session_row, state.step)

    return MessageResponse(
            messages=[bot_reply], step=state.step, candidate=vars(state.candidate), extracted=extracted,
        )
@router.post("/sessions/{session_id}/resume/confirm", response_model=MessageResponse)
def confirm_resume_data(session_id: str, body: ConfirmResumeRequest, db: SQLASession = Depends(get_db)):
    state = ACTIVE_SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if state.step not in ("confirm_resume_data",):
        raise HTTPException(status_code=400, detail="Not expecting resume confirmation right now")

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    session_row = get_session_or_404(db, session_uuid)

    state.pending_resume_data = {
        "email": body.email or None,
        "phone": body.phone or None,
        "location": body.location or None,
        "experience": body.experience or None,
        "role": body.role or None,
        "tech_stack": body.tech_stack or [],
        "education": body.education or None,
        "linkedin": body.linkedin or None,
        "github": body.github or None,
    }

    # catch duplicate email BEFORE it ever reaches the database
    if body.email:
        candidate_row = get_candidate_or_404(db, session_row.candidate_id)
        duplicate = (
            db.query(Candidate)
            .filter(
                Candidate.org_id == candidate_row.org_id,
                Candidate.email == body.email,
                Candidate.id != session_row.candidate_id,
            )
            .first()
        )
        if duplicate is not None:
            duplicate_session = db.query(SessionModel).filter(SessionModel.candidate_id == duplicate.id).first()
            duplicate_completed = duplicate_session is not None and duplicate_session.status == "completed"

            if duplicate_completed:
                # A genuinely finished screening already exists under this email —
                # no choice to offer, this is a real duplicate.
                msg = "That email is already registered with another screening. Please edit the email field and try again."
                db.add(Message(session_id=session_uuid, role="assistant", content=msg))
                db.commit()
                return MessageResponse(
                    messages=[msg], step=state.step, candidate=vars(state.candidate), extracted=state.pending_resume_data
                )

            if not body.replace_duplicate:
                # An earlier attempt under this email exists but never completed —
                # let the candidate decide rather than silently blocking or silently
                # deleting someone else's (or their own) abandoned attempt.
                msg = (
                    "There's an earlier, unfinished screening under this email. "
                    "You can use a different email, or delete that old attempt and continue here with this one."
                )
                db.add(Message(session_id=session_uuid, role="assistant", content=msg))
                db.commit()
                return MessageResponse(
                    messages=[msg], step=state.step, candidate=vars(state.candidate),
                    extracted=state.pending_resume_data, duplicate_email_choice=True,
                )

            # Candidate chose to replace — the cascade-delete chain (see
            # migrate_cascade_deletes.py) cleans up the old candidate's session,
            # messages, logs, and any MCQ data automatically.
            db.delete(duplicate)
            db.commit()
    if not body.email or not is_valid_email(body.email):
        msg = "That doesn't look like a valid email address — please fix it and confirm again."
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))
        db.commit()
        return MessageResponse(messages=[msg], step=state.step, candidate=vars(state.candidate), extracted=state.pending_resume_data)

    if not body.phone or not is_valid_phone(body.phone):
        msg = "That doesn't look like a valid phone number — please fix it and confirm again."
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))
        db.commit()
        return MessageResponse(messages=[msg], step=state.step, candidate=vars(state.candidate), extracted=state.pending_resume_data)

    if body.experience and not is_valid_experience(body.experience):
        msg = 'Experience should be a number, like "2" or "2.5" — please fix it and confirm again.'
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))
        db.commit()
        return MessageResponse(messages=[msg], step=state.step, candidate=vars(state.candidate), extracted=state.pending_resume_data)

    db.add(Message(session_id=session_uuid, role="user", content="[confirmed edited resume data]"))
    result = handle_user_input(state, "yes")
    state = result.state
    ACTIVE_SESSIONS[session_id] = state

    for msg in result.bot_messages:
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))

    _mark_step(db, session_uuid, session_row, state.step, exited_early=result.exited_early)
    
    _sync_candidate_row(db, session_row.candidate_id, state)

    bot_messages = list(result.bot_messages)

    return MessageResponse(messages=bot_messages, step=state.step, candidate=vars(state.candidate))