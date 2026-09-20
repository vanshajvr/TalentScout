import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Session as SessionModel, MCQAssessment, MCQAnswer, MCQQuestion
from deps import get_session_or_404, get_candidate_or_404
from utils.constants import (
    MCQ_TECHNICAL_COUNT, MCQ_BEHAVIORAL_COUNT, MCQ_OPEN_TEXT_COUNT, MCQ_TOTAL_COUNT,
    MCQ_TECHNICAL_TIME_LIMIT_SECONDS, MCQ_OPEN_TEXT_MAX_CHARS, MCQ_FORMATS, MCQ_DIFFICULTY_TIERS,
    BEHAVIORAL_QUESTION_TEMPLATES,
)
from routers.candidate import _difficulty_tier, _load_prompt, _mark_step
from utils.llm_json import parse_llm_json
from llm.groq_llm import GroqLLM

router = APIRouter(prefix="/sessions/{session_id}/mcq")

llm = GroqLLM()

# A couple of seconds of pure network-latency tolerance — distinct from the "banked grace"
# mechanic that was deliberately dropped in favor of a flat, transparent 60s per question.
NETWORK_LATENCY_BUFFER_SECONDS = 2

BEHAVIORAL_DIMENSIONS = [
    "collaboration style (independent vs. team-oriented)",
    "risk tolerance under ambiguity",
    "receptiveness to feedback",
    "prioritization under time pressure",
    "sense of ownership and accountability",
]


class MCQQuestionResponse(BaseModel):
    completed: bool = False
    question_index: int | None = None
    total_questions: int = MCQ_TOTAL_COUNT
    question_type: str | None = None  # technical | behavioral | open_text
    question_text: str | None = None
    options: list[dict] | None = None
    max_chars: int | None = None
    remaining_time_seconds: int | None = None


class MCQAnswerRequest(BaseModel):
    selected_option_id: str | None = None
    text_response: str | None = None


class TabSwitchResponse(BaseModel):
    tab_switch_count: int
    fullscreen_exit_count: int


class IntegrityEventRequest(BaseModel):
    event_type: str  # "tab_switch" | "fullscreen_exit"


def _starting_difficulty_tier(candidate) -> str:
    tier = _difficulty_tier(candidate.experience)
    return tier if tier in MCQ_DIFFICULTY_TIERS else "applied"  # "unknown" -> safe middle default


def _adjust_difficulty(current_tier: str, last_two_correct: list[bool]) -> str:
    idx = MCQ_DIFFICULTY_TIERS.index(current_tier)
    if last_two_correct == [True, True]:
        idx = min(idx + 1, len(MCQ_DIFFICULTY_TIERS) - 1)
    elif last_two_correct == [False, False]:
        idx = max(idx - 1, 0)
    return MCQ_DIFFICULTY_TIERS[idx]


def _tech_for_index(tech_stack: list[str] | None, index: int) -> str:
    if not tech_stack:
        return "General Programming"
    return tech_stack[index % len(tech_stack)]


def _sample_technical_question(
    db: SQLASession, technology: str, difficulty_tier: str, exclude_ids: list[uuid.UUID]
) -> MCQQuestion | None:
    def _query_for(tech: str):
        return db.query(MCQQuestion).filter(
            MCQQuestion.technology == tech,
            MCQQuestion.difficulty_tier == difficulty_tier,
            MCQQuestion.active.is_(True),
        )

    for tech in (technology, "General Programming"):
        base_query = _query_for(tech)
        if exclude_ids:
            question = base_query.filter(MCQQuestion.id.notin_(exclude_ids)).order_by(func.random()).first()
            if question is not None:
                return question
        # Pool exhausted at this (technology, tier) without repeats — better to serve a
        # repeat than fail the assessment outright.
        question = base_query.order_by(func.random()).first()
        if question is not None:
            return question
        # Nothing at all for this technology (candidate's stack includes something the
        # pool hasn't been seeded for yet) — fall back to the always-seeded generic bucket
        # rather than failing the whole assessment over one niche technology.
    return None


def _generate_behavioral_question(candidate, already_asked: list[str], dimension: str) -> dict:
    prompt_template = _load_prompt("prompts/behavioral_mcq_prompt.txt")
    prompt = prompt_template.format(
        role=candidate.role or "the applied role",
        experience=candidate.experience if candidate.experience is not None else "unspecified",
        tech_stack=", ".join(candidate.tech_stack) if candidate.tech_stack else "unspecified",
        resume_excerpt=(candidate.resume_text or "")[:3000],
        dimension=dimension,
        already_asked="\n".join(f"- {q}" for q in already_asked) if already_asked else "(none yet)",
    )
    try:
        raw = llm.generate(prompt, temperature=0.7).strip()
        parsed = parse_llm_json(raw)
        if not parsed.get("question_text") or len(parsed.get("options", [])) != 4:
            raise ValueError("malformed behavioral question response")
        return parsed
    except Exception as e:
        print(f"Behavioral MCQ generation failed: {e}")
        # Fall back to a generic, still-valid scenario rather than breaking the assessment.
        return {
            "question_text": (
                f"You're partway through a task related to your work as {candidate.role or 'a candidate'} "
                "when priorities shift unexpectedly. What's your instinct?"
            ),
            "options": [
                {"id": "a", "text": "Finish what I started before switching focus."},
                {"id": "b", "text": "Drop it immediately and address the new priority."},
                {"id": "c", "text": "Check in with others before deciding how to proceed."},
                {"id": "d", "text": "Quickly assess impact, then decide on my own."},
            ],
        }


def _serve_question(db: SQLASession, assessment: MCQAssessment, candidate) -> MCQAnswer | None:
    """Returns the currently-active MCQAnswer for this assessment, creating it on first
    visit to this index. Returns None once the assessment is complete."""
    if assessment.status == "completed":
        return None

    existing = db.query(MCQAnswer).filter(
        MCQAnswer.assessment_id == assessment.id,
        MCQAnswer.question_index == assessment.current_question_index,
    ).first()
    if existing is not None:
        return existing  # resume case — already served, not yet answered

    index = assessment.current_question_index
    now = datetime.utcnow()

    if index < MCQ_TECHNICAL_COUNT:
        if index == 0:
            difficulty_tier = _starting_difficulty_tier(candidate)
        else:
            last_two = db.query(MCQAnswer).filter(
                MCQAnswer.assessment_id == assessment.id, MCQAnswer.question_type == "technical"
            ).order_by(MCQAnswer.question_index.desc()).limit(2).all()
            last_two_correct: list[bool] = [bool(a.is_correct) for a in reversed(last_two)]
            prev_tier = (
                last_two[0].difficulty_tier
                if last_two and last_two[0].difficulty_tier else _starting_difficulty_tier(candidate)
            )
            difficulty_tier = _adjust_difficulty(prev_tier, last_two_correct)

        technology = _tech_for_index(candidate.tech_stack, index)
        already_served_ids: list[uuid.UUID] = [
            a.pool_question_id for a in db.query(MCQAnswer).filter(
                MCQAnswer.assessment_id == assessment.id, MCQAnswer.question_type == "technical",
                MCQAnswer.pool_question_id.isnot(None),
            ).all()
            if a.pool_question_id is not None
        ]
        question = _sample_technical_question(db, technology, difficulty_tier, already_served_ids)
        if question is None:
            raise HTTPException(
                status_code=503,
                detail=f"No technical questions available for {technology} at {difficulty_tier} level yet",
            )
        answer = MCQAnswer(
            assessment_id=assessment.id, question_index=index, question_type="technical",
            pool_question_id=question.id, question_text=question.question_text,
            options_snapshot=question.options, difficulty_tier=difficulty_tier,
            question_started_at=now,
        )

    elif index < MCQ_TECHNICAL_COUNT + MCQ_BEHAVIORAL_COUNT:
        behavioral_position = index - MCQ_TECHNICAL_COUNT
        dimension = BEHAVIORAL_DIMENSIONS[behavioral_position]
        already_asked = [
            a.question_text for a in db.query(MCQAnswer).filter(
                MCQAnswer.assessment_id == assessment.id, MCQAnswer.question_type == "behavioral",
            ).order_by(MCQAnswer.question_index).all()
        ]
        generated = _generate_behavioral_question(candidate, already_asked, dimension)
        answer = MCQAnswer(
            assessment_id=assessment.id, question_index=index, question_type="behavioral",
            pool_question_id=None, question_text=generated["question_text"],
            options_snapshot=generated["options"], question_started_at=now,
        )

    else:
        open_text_position = index - MCQ_TECHNICAL_COUNT - MCQ_BEHAVIORAL_COUNT
        role = candidate.role or "this role"
        template = BEHAVIORAL_QUESTION_TEMPLATES[open_text_position]
        question_text = template.format(role=role, role_lower=role.lower())
        answer = MCQAnswer(
            assessment_id=assessment.id, question_index=index, question_type="open_text",
            pool_question_id=None, question_text=question_text, options_snapshot=None,
            question_started_at=now,
        )

    db.add(answer)
    try:
        db.commit()
    except IntegrityError:
        # Another concurrent request (double-click, second tab) already created the
        # answer row at this exact question_index between our check and our insert.
        db.rollback()
        existing = db.query(MCQAnswer).filter(
            MCQAnswer.assessment_id == assessment.id, MCQAnswer.question_index == index,
        ).first()
        if existing is None:
            raise  # genuinely unexpected — not the race we were guarding against
        return existing
    db.refresh(answer)
    return answer


def _to_response(answer: MCQAnswer | None) -> MCQQuestionResponse:
    if answer is None:
        return MCQQuestionResponse(completed=True)

    remaining = None
    if answer.question_type == "technical":
        elapsed = (datetime.utcnow() - answer.question_started_at).total_seconds()
        remaining = max(0, round(MCQ_TECHNICAL_TIME_LIMIT_SECONDS - elapsed))

    return MCQQuestionResponse(
        completed=False,
        question_index=answer.question_index,
        question_type=answer.question_type,
        question_text=answer.question_text,
        options=answer.options_snapshot,
        max_chars=MCQ_OPEN_TEXT_MAX_CHARS if answer.question_type == "open_text" else None,
        remaining_time_seconds=remaining,
    )


def _get_session_and_candidate(session_id: str, db: SQLASession):
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")
    session_row = get_session_or_404(db, session_uuid)
    candidate = get_candidate_or_404(db, session_row.candidate_id)
    return session_uuid, session_row, candidate


@router.get("/current", response_model=MCQQuestionResponse)
def get_current_question(session_id: str, db: SQLASession = Depends(get_db)):
    session_uuid, session_row, candidate = _get_session_and_candidate(session_id, db)

    assessment = db.query(MCQAssessment).filter(MCQAssessment.session_id == session_uuid).first()
    if assessment is None:
        assessment = MCQAssessment(session_id=session_uuid)
        db.add(assessment)
        try:
            db.commit()
        except IntegrityError:
            # Another concurrent request already created the assessment for this session
            # between our check and our insert.
            db.rollback()
            assessment = db.query(MCQAssessment).filter(MCQAssessment.session_id == session_uuid).first()
            if assessment is None:
                raise  # genuinely unexpected — not the race we were guarding against
        else:
            db.refresh(assessment)

    answer = _serve_question(db, assessment, candidate)
    return _to_response(answer)


@router.post("/answer", response_model=MCQQuestionResponse)
def submit_answer(session_id: str, body: MCQAnswerRequest, db: SQLASession = Depends(get_db)):
    session_uuid, session_row, candidate = _get_session_and_candidate(session_id, db)

    assessment = db.query(MCQAssessment).filter(MCQAssessment.session_id == session_uuid).first()
    if assessment is None or assessment.status == "completed":
        raise HTTPException(status_code=409, detail="No active question to answer")

    answer = db.query(MCQAnswer).filter(
        MCQAnswer.assessment_id == assessment.id,
        MCQAnswer.question_index == assessment.current_question_index,
    ).first()
    if answer is None:
        raise HTTPException(status_code=409, detail="No active question — fetch the current question first")
    if answer.answered_at is not None:
        raise HTTPException(status_code=409, detail="This question has already been answered")

    now = datetime.utcnow()
    elapsed = (now - answer.question_started_at).total_seconds()

    if answer.question_type == "technical":
        is_late = elapsed > (MCQ_TECHNICAL_TIME_LIMIT_SECONDS + NETWORK_LATENCY_BUFFER_SECONDS)
        no_selection = not body.selected_option_id
        if is_late or no_selection:
            # No selection at all is always treated as a timeout, even inside the grace
            # window — otherwise a client auto-submitting with null right as its local
            # timer hits 0 (a couple seconds before the server's own deadline) gets
            # rejected as an invalid option id instead of just being marked unanswered.
            answer.selected_option_id = None
            answer.is_correct = False
            answer.time_taken_seconds = MCQ_TECHNICAL_TIME_LIMIT_SECONDS
        else:
            valid_ids = {opt["id"] for opt in (answer.options_snapshot or [])}
            if body.selected_option_id not in valid_ids:
                raise HTTPException(status_code=400, detail="selected_option_id does not match any option for this question")
            pool_question = db.get(MCQQuestion, answer.pool_question_id)
            if pool_question is None:
                # Shouldn't happen in practice (pool_question_id is only set when a real
                # MCQQuestion was just sampled), but guards against a deleted/corrupted row.
                raise HTTPException(status_code=500, detail="Referenced question no longer exists")
            answer.selected_option_id = body.selected_option_id
            answer.is_correct = (body.selected_option_id == pool_question.correct_option_id)
            answer.time_taken_seconds = min(round(elapsed), MCQ_TECHNICAL_TIME_LIMIT_SECONDS)

    elif answer.question_type == "behavioral":
        valid_ids = {opt["id"] for opt in (answer.options_snapshot or [])}
        if body.selected_option_id not in valid_ids:
            raise HTTPException(status_code=400, detail="selected_option_id does not match any option for this question")
        answer.selected_option_id = body.selected_option_id
        answer.time_taken_seconds = round(elapsed)

    else:  # open_text
        text = (body.text_response or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text_response is required")
        if len(text) > MCQ_OPEN_TEXT_MAX_CHARS:
            raise HTTPException(status_code=400, detail=f"Response exceeds the {MCQ_OPEN_TEXT_MAX_CHARS}-character limit")
        answer.text_response = text
        answer.time_taken_seconds = round(elapsed)

    answer.answered_at = now

    assessment.current_question_index += 1
    is_last = assessment.current_question_index >= MCQ_TOTAL_COUNT
    if is_last:
        assessment.status = "completed"
        assessment.completed_at = now

    db.commit()  # answer + index bump (+ completion, if last) commit together — a crash
                 # between them previously left the candidate stuck on "already answered"
                 # with no way to advance, since the index was never bumped.

    if is_last:
        # NOTE: goes straight to "end" for now. Once the recruiter live-join feature lands,
        # this should transition to an intermediate step instead, per the 90s live-join
        # window design in the progress doc.
        _mark_step(db, session_uuid, session_row, "end")
        return MCQQuestionResponse(completed=True)
    next_answer = _serve_question(db, assessment, candidate)
    return _to_response(next_answer)


@router.post("/integrity-event", response_model=TabSwitchResponse)
def record_integrity_event(session_id: str, body: IntegrityEventRequest, db: SQLASession = Depends(get_db)):
    if body.event_type not in ("tab_switch", "fullscreen_exit"):
        raise HTTPException(status_code=400, detail="event_type must be 'tab_switch' or 'fullscreen_exit'")

    session_uuid, _, _ = _get_session_and_candidate(session_id, db)

    assessment = db.query(MCQAssessment).filter(MCQAssessment.session_id == session_uuid).first()
    if assessment is None:
        raise HTTPException(status_code=404, detail="No active assessment for this session")

    current_answer = db.query(MCQAnswer).filter(
        MCQAnswer.assessment_id == assessment.id,
        MCQAnswer.question_index == assessment.current_question_index,
    ).first()

    if body.event_type == "tab_switch":
        assessment.tab_switch_count += 1
        if current_answer is not None:
            current_answer.tab_switch_count += 1
    else:
        assessment.fullscreen_exit_count += 1
        if current_answer is not None:
            current_answer.fullscreen_exit_count += 1

    db.commit()
    return TabSwitchResponse(
        tab_switch_count=assessment.tab_switch_count,
        fullscreen_exit_count=assessment.fullscreen_exit_count,
    )