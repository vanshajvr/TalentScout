import uuid
import copy
import secrets
import os

import smtplib
from email.mime.text import MIMEText

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion
from conversation import ConversationState, handle_user_input, get_bot_message, next_step
from llm.ollama_llm import OllamaLLM
from utils.constants import BEHAVIORAL_QUESTION_TEMPLATES
from deps import get_candidate_or_404, get_session_or_404

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

llm = OllamaLLM()
ACTIVE_SESSIONS: dict[str, ConversationState] = {}

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

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


def _load_prompt(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


_SYSTEM_PROMPT = _load_prompt("prompts/system_prompt.txt")


def _generate_mock_otp() -> str:
    return str(secrets.randbelow(1_000_000)).zfill(6)


def _sync_candidate_row(db: SQLASession, candidate_id: uuid.UUID, state: ConversationState) -> None:
    row = get_candidate_or_404(db, candidate_id)
    c = state.candidate
    row.name = c.name or None
    row.email = c.email or None
    row.phone = c.phone or None
    row.location = c.location or None
    row.experience = float(c.experience.replace("+", "")) if c.experience else None
    row.role = c.role or None
    row.tech_stack = c.tech_stack or None
    row.email_verified = c.email_verified
    row.phone_verified = c.phone_verified
    db.commit()


def _difficulty_tier(experience: str) -> str:
    try:
        val = float(experience.replace("+", ""))
    except ValueError:
        return "unknown"
    if val < 1:
        return "fundamentals"
    if val <= 3:
        return "applied"
    return "advanced"


def _format_history(qa_history: list[tuple[str, str]]) -> str:
    if not qa_history:
        return "(none yet)"
    return "\n\n".join(f"Q: {q}\nA: {a}" for q, a in qa_history)


def _generate_next_question(state: ConversationState) -> str:
    plan_item = state.interview_plan[state.interview_index]
    role = state.candidate.role

    if plan_item == "behavioral_role":
        return BEHAVIORAL_QUESTION_TEMPLATES[0].format(role=role)
    if plan_item == "behavioral_stream":
        return BEHAVIORAL_QUESTION_TEMPLATES[1].format(role=role, role_lower=role.lower())

    prompt_template = _load_prompt("prompts/next_question_prompt.txt")
    prompt = prompt_template.format(
        role=role,
        experience=state.candidate.experience,
        technology=plan_item,
        qa_history=_format_history(state.qa_history),
    )
    try:
        return llm.generate(prompt, system=_SYSTEM_PROMPT).strip()
    except Exception as e:
        print(f"LLM generation failed: {e}")
        return (
            f"(We're having trouble generating a tailored question right now — "
            f"tell me about your experience with {plan_item}.)"
        )


@router.post("/sessions", response_model=StartSessionResponse)
def start_session(db: SQLASession = Depends(get_db)):
    candidate_row = Candidate()
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
    prev_question = state.current_question if state.step == "interviewing" else None
    was_ask_email_step = state.step == "ask_email"
    state_snapshot = copy.deepcopy(state)

    result = handle_user_input(state, body.text)
    state = result.state

    if was_ask_email_step and state.candidate.email:
        duplicate = (
            db.query(Candidate)
            .filter(Candidate.email == state.candidate.email, Candidate.id != session_row.candidate_id)
            .first()
        )
        if duplicate is not None:
            state = state_snapshot
            ACTIVE_SESSIONS[session_id] = state
            msg = "That email is already registered with another screening. Please use a different email address."
            db.add(Message(session_id=session_uuid, role="assistant", content=msg))
            db.commit()
            return MessageResponse(messages=[msg], step=state.step, candidate=vars(state.candidate))

    ACTIVE_SESSIONS[session_id] = state

    for msg in result.bot_messages:
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))

    session_row.current_step = state.step
    db.commit()

    _sync_candidate_row(db, session_row.candidate_id, state)

    if prev_question:
        q_row = (
            db.query(GeneratedQuestion)
            .filter_by(session_id=session_uuid, question_text=prev_question)
            .first()
        )
        if q_row is not None:
            q_row.answer_text = body.text
            db.commit()

    bot_messages = list(result.bot_messages)

    if state.step == "interviewing" and not state.current_question:
        question_text = _generate_next_question(state)
        state.current_question = question_text
        ACTIVE_SESSIONS[session_id] = state

        plan_item = state.interview_plan[state.interview_index]
        db.add(GeneratedQuestion(
            session_id=session_uuid,
            technology=plan_item,
            question_text=question_text,
            difficulty_tier=_difficulty_tier(state.candidate.experience),
            answer_text=None,
        ))
        db.add(Message(session_id=session_uuid, role="assistant", content=question_text))
        db.commit()
        bot_messages.append(question_text)

    if state.step in ("verify_email", "verify_phone") and not state.pending_otp:
        code = _generate_mock_otp()
        state.pending_otp = code
        ACTIVE_SESSIONS[session_id] = state

        if state.step == "verify_email":
            target = state.candidate.email
            sent = _send_otp_email(target, code)
            if sent:
                msg = f"We've sent a 6-digit verification code to {target}. Please enter it below."
            else:
                # SMTP not configured — don't block testing, show the code directly
                msg = f"(Email delivery isn't configured yet — for testing, your code is: {code})"
        else:
            # phone verification stays mock until Firebase is wired in
            target = state.candidate.phone
            msg = (
                f"[DEV MODE — mock OTP, not actually sent]\n"
                f"Your verification code for {target} is: **{code}**\n"
                f"(Real SMS via Firebase coming soon — you're seeing it directly here for now.)"
            )

        db.add(Message(session_id=session_uuid, role="assistant", content=msg))
        db.commit()
        bot_messages.append(msg)

    if state.step == "end" and session_row.status != "completed":
        session_row.status = "completed"
        db.commit()

    return MessageResponse(messages=bot_messages, step=state.step, candidate=vars(state.candidate))


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

    safe_name = f"{session_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(file.file.read())

    session_row = get_session_or_404(db, session_uuid)
    candidate_row = get_candidate_or_404(db, session_row.candidate_id)
    candidate_row.resume_filename = file.filename
    candidate_row.resume_path = dest_path
    db.commit()

    state.step = next_step(state.step)
    ACTIVE_SESSIONS[session_id] = state

    bot_reply = get_bot_message(state)
    db.add(Message(session_id=session_uuid, role="user", content=f"[uploaded resume: {file.filename}]"))
    db.add(Message(session_id=session_uuid, role="assistant", content=bot_reply))
    session_row.current_step = state.step
    db.commit()

    return MessageResponse(messages=[bot_reply], step=state.step, candidate=vars(state.candidate))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: SQLASession = Depends(get_db)):
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    session_row = get_session_or_404(db, session_uuid)
    candidate_row = get_candidate_or_404(db, session_row.candidate_id)

    return {
        "session_id": session_id,
        "step": session_row.current_step,
        "status": session_row.status,
        "candidate": {
            "name": candidate_row.name,
            "email": candidate_row.email,
            "phone": candidate_row.phone,
            "location": candidate_row.location,
            "experience": candidate_row.experience,
            "role": candidate_row.role,
            "tech_stack": candidate_row.tech_stack,
        },
    }

def _send_otp_email(to_email: str, code: str) -> bool:
    if not SMTP_USER or not SMTP_PASSWORD:
        return False  # not configured — caller falls back to showing the code in chat

    smtp_user: str = SMTP_USER
    smtp_password: str = SMTP_PASSWORD
    smtp_from: str = SMTP_FROM or smtp_user

    body = (
        f"Your TalentScout verification code is: {code}\n\n"
        f"If you didn't request this, you can ignore this email."
    )
    msg = MIMEText(body)
    msg["Subject"] = "Your TalentScout verification code"
    msg["From"] = smtp_from
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"OTP email send failed: {e}")
        return False