import uuid

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, Session as SessionModel, Message, GeneratedQuestion
from conversation import ConversationState, CandidateState, handle_user_input, get_bot_message
from llm.ollama_llm import OllamaLLM

app = FastAPI(title="TalentScout API")
llm = OllamaLLM()

ACTIVE_SESSIONS: dict[str, ConversationState] = {}


class StartSessionResponse(BaseModel):
    session_id: str
    message: str


class MessageRequest(BaseModel):
    text: str


class MessageResponse(BaseModel):
    messages: list[str]
    step: str
    candidate: dict


def _load_prompt(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def _get_candidate_or_404(db: SQLASession, candidate_id: uuid.UUID) -> Candidate:
    row = db.get(Candidate, candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


def _get_session_or_404(db: SQLASession, session_id: uuid.UUID) -> SessionModel:
    row = db.get(SessionModel, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


def _sync_candidate_row(db: SQLASession, candidate_id: uuid.UUID, state: ConversationState) -> None:
    row = _get_candidate_or_404(db, candidate_id)
    c = state.candidate
    row.name = c.name or None
    row.email = c.email or None
    row.phone = c.phone or None
    row.location = c.location or None
    row.experience = float(c.experience.replace("+", "")) if c.experience else None
    row.role = c.role or None
    row.tech_stack = c.tech_stack or None
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


@app.post("/sessions", response_model=StartSessionResponse)
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


@app.post("/sessions/{session_id}/messages", response_model=MessageResponse)
def post_message(session_id: str, body: MessageRequest, db: SQLASession = Depends(get_db)):
    state = ACTIVE_SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    db.add(Message(session_id=session_uuid, role="user", content=body.text))

    result = handle_user_input(state, body.text)
    state = result.state
    ACTIVE_SESSIONS[session_id] = state

    for msg in result.bot_messages:
        db.add(Message(session_id=session_uuid, role="assistant", content=msg))

    session_row = _get_session_or_404(db, session_uuid)
    session_row.current_step = state.step
    db.commit()

    _sync_candidate_row(db, session_row.candidate_id, state)

    bot_messages = list(result.bot_messages)

    if state.step == "generate_questions":
        prompt_template = _load_prompt("prompts/tech_questions_prompt.txt")
        filled_prompt = prompt_template.format(
            role=state.candidate.role,
            experience=state.candidate.experience,
            tech_stack=", ".join(state.candidate.tech_stack),
        )
        questions_text = llm.generate(filled_prompt)

        db.add(GeneratedQuestion(
            session_id=session_uuid,
            technology=", ".join(state.candidate.tech_stack),
            question_text=questions_text,
            difficulty_tier=_difficulty_tier(state.candidate.experience),
        ))
        db.add(Message(session_id=session_uuid, role="assistant", content=questions_text))

        state.step = "end"
        session_row.current_step = "end"
        session_row.status = "completed"
        db.commit()
        ACTIVE_SESSIONS[session_id] = state

        bot_messages.append(questions_text)
        closing = get_bot_message(state)
        db.add(Message(session_id=session_uuid, role="assistant", content=closing))
        db.commit()
        bot_messages.append(closing)

    return MessageResponse(
        messages=bot_messages,
        step=state.step,
        candidate=vars(state.candidate),
    )


@app.get("/sessions/{session_id}")
def get_session(session_id: str, db: SQLASession = Depends(get_db)):
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    session_row = _get_session_or_404(db, session_uuid)
    candidate_row = _get_candidate_or_404(db, session_row.candidate_id)

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
