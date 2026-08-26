import uuid
import copy
import secrets
import os

import pdfplumber
from docx import Document as DocxDocument
import json

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion, SessionLog
from conversation import ConversationState, handle_user_input, get_bot_message
from llm.groq_llm import GroqLLM
from utils.constants import BEHAVIORAL_QUESTION_TEMPLATES
from utils.validators import is_valid_email, is_valid_phone
from deps import get_candidate_or_404, get_session_or_404

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

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

class ConfirmResumeRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    experience: str | None = None
    role: str | None = None
    tech_stack: list[str] | None = None
    education: str | None = None
    linkedin: str | None = None
    github: str | None = None

def _extract_resume_text(file_path: str, ext: str) -> str:
    if ext == ".pdf":
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
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

def _extract_resume_fields(resume_text: str) -> dict:
    if not resume_text.strip():
        return {}
    prompt_template = _load_prompt("prompts/resume_extraction_prompt.txt")
    prompt = prompt_template.format(resume_text=resume_text[:6000])
    try:
        raw = llm.generate(prompt, temperature=0).strip()
        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "", 1).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Resume extraction failed: {e}")
        return {}
    
def _load_prompt(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


_SYSTEM_PROMPT = _load_prompt("prompts/system_prompt.txt")


def _sync_candidate_row(db: SQLASession, candidate_id: uuid.UUID, state: ConversationState) -> None:
    row = get_candidate_or_404(db, candidate_id)
    c = state.candidate
    row.name = c.name or None
    row.email = c.email or None
    row.education = c.education or None
    row.phone = c.phone or None
    row.location = c.location or None
    row.experience = float(c.experience.replace("+", "")) if c.experience else None
    row.role = c.role or None
    row.tech_stack = c.tech_stack or None
    row.email_verified = c.email_verified
    row.phone_verified = c.phone_verified
    row.linkedin_url = c.linkedin or None
    row.github_url = c.github or None
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

def _log_event(db: SQLASession, session_uuid: uuid.UUID, event_type: str, detail: str):
    db.add(SessionLog(session_id=session_uuid, event_type=event_type, detail=detail))
    db.commit()

def _format_history(qa_history: list[tuple[str, str]]) -> str:
    if not qa_history:
        return "(none yet)"
    return "\n\n".join(f"Q: {q}\nA: {a}" for q, a in qa_history)


def _generate_next_question(state: ConversationState) -> str:
    if state.interview_index >= len(state.interview_plan):
        return "Thank you — that's all the questions I have for now."
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
    
def _score_answer(question_text: str, answer_text: str, technology: str, experience: str) -> dict:
    prompt_template = _load_prompt("prompts/answer_scoring_prompt.txt")
    prompt = prompt_template.format(
        question_text=question_text,
        answer_text=answer_text,
        technology=technology,
        experience=experience,
    )
    try:
        raw = llm.generate(prompt, temperature=0).strip()
        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "", 1).strip()
        result = json.loads(raw)
        return {
            "correctness": int(result["correctness"]),
            "reasoning": int(result["reasoning"]),
            "communication": int(result["communication"]),
            "justification": result.get("justification"),
        }
    
    except Exception as e:
        print(f"Answer scoring failed: {e}")
        return {"correctness": None, "reasoning": None, "communication": None, "justification": None}
        
    
def _post_process_turn(state, session_uuid, db, session_row, bot_messages):
    if state.step == "interviewing" and not state.current_question and not state.current_question:
        question_text = _generate_next_question(state)
        state.current_question = question_text
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

    if state.step == "end" and session_row.status != "completed":
        session_row.status = "completed"
        db.commit()

    return state, bot_messages


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
    if session_row.current_step != state.step:
        _log_event(db, session_uuid, "step_transition", f"{session_row.current_step} -> {state.step}")
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
            score = _score_answer(q_row.question_text, body.text, q_row.technology, state.candidate.experience)
            q_row.correctness_score = score["correctness"]
            q_row.reasoning_score = score["reasoning"]
            q_row.communication_score = score["communication"]
            q_row.score_justification = score["justification"]
            db.commit()

    bot_messages = list(result.bot_messages)
    state, bot_messages = _post_process_turn(state, session_uuid, db, session_row, bot_messages)
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

    safe_name = f"{session_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(file.file.read())

    session_row = get_session_or_404(db, session_uuid)
    candidate_row = get_candidate_or_404(db, session_row.candidate_id)
    candidate_row.resume_filename = file.filename
    candidate_row.resume_path = dest_path
    db.commit()

    resume_text = _extract_resume_text(dest_path, ext)
    extracted = _extract_resume_fields(resume_text)
    state.pending_resume_data = extracted

    extracted = _extract_resume_fields(resume_text)
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
    session_row.current_step = state.step
    if session_row.current_step != state.step:
        _log_event(db, session_uuid, "step_transition", f"{session_row.current_step} -> {state.step}")
    session_row.current_step = state.step
    db.commit()

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
        duplicate = (
            db.query(Candidate)
            .filter(Candidate.email == body.email, Candidate.id != session_row.candidate_id)
            .first()
        )
        if duplicate is not None:
            msg = "That email is already registered with another screening. Please edit the email field and try again."
            db.add(Message(session_id=session_uuid, role="assistant", content=msg))
            db.commit()
            return MessageResponse(
                messages=[msg], step=state.step, candidate=vars(state.candidate), extracted=state.pending_resume_data
            )
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

    db.add(Message(session_id=session_uuid, role="user", content="[confirmed edited resume data]"))
    result = handle_user_input(state, "yes")
    state = result.state
    ACTIVE_SESSIONS[session_id] = state

    for msg in result.bot_messages:
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))

    session_row.current_step = state.step
    if session_row.current_step != state.step:
        _log_event(db, session_uuid, "step_transition", f"{session_row.current_step} -> {state.step}")
    session_row.current_step = state.step
    db.commit()
    _sync_candidate_row(db, session_row.candidate_id, state)

    bot_messages = list(result.bot_messages)
    state, bot_messages = _post_process_turn(state, session_uuid, db, session_row, bot_messages)

    return MessageResponse(messages=bot_messages, step=state.step, candidate=vars(state.candidate))