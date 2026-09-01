from dataclasses import dataclass, field

from utils.constants import STEPS, EXIT_KEYWORDS, MAX_TECHNICAL_QUESTIONS
from utils.validators import (
    is_valid_name,
    is_valid_email,
    is_valid_phone,
    is_valid_experience,
)


@dataclass
class CandidateState:
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    experience: str = ""
    role: str = ""
    tech_stack: list[str] = field(default_factory=list)
    education: str = ""
    linkedin: str = ""
    github: str = ""


@dataclass
class ConversationState:
    step: str = "greeting"
    candidate: CandidateState = field(default_factory=CandidateState)
    retry: bool = False
    pending_resume_data: dict = field(default_factory=dict)
    interview_plan: list[str] = field(default_factory=list)
    interview_index: int = 0
    current_question: str = ""
    qa_history: list[tuple[str, str]] = field(default_factory=list)

def next_step(current_step: str) -> str:
    idx = STEPS.index(current_step)
    return STEPS[min(idx + 1, len(STEPS) - 1)]


def seems_uncertain(text: str) -> bool:
    low_confidence_phrases = {
        "idk", "not sure", "maybe", "dont know", "don't know", "unsure"
    }
    return any(p in text.lower() for p in low_confidence_phrases)


def get_bot_message(state: ConversationState) -> str:
    step = state.step
    if step == "greeting":
        return (
            "Hello! 👋 I'm TalentScout's Hiring Assistant. "
            "I'll ask you a few questions for initial screening. "
            "Type **hi** or **hello** to begin, or **exit** anytime to end the conversation."
        )
    if step == "ask_name":
        return "Let's begin. What's your full name?"
    if step == "upload_resume":
        return "Please upload your resume/CV (PDF or DOCX) to continue."
    if step == "confirm_resume_data":
        return ""  # main.py already sent this via the /resume endpoint
    if step == "interviewing":
        return ""
    if step == "end":
        return (
            "Thank you for your time. 🙏 "
            "Our team will review your responses and get back to you soon. "
            "Have a great day!"
        )
    return ""


@dataclass
class StepResult:
    state: ConversationState
    bot_messages: list[str]


def _build_interview_plan(tech_stack: list[str]) -> list[str]:
    technical = tech_stack[:MAX_TECHNICAL_QUESTIONS]
    return technical + ["behavioral_role", "behavioral_stream"]


def handle_user_input(state: ConversationState, user_input: str) -> StepResult:
    user_input_clean = user_input.strip().lower()
    bot_messages: list[str] = []
    candidate = state.candidate

    if user_input_clean in EXIT_KEYWORDS:
        state.step = "end"
        bot_messages.append(get_bot_message(state))
        return StepResult(state=state, bot_messages=bot_messages)

    if seems_uncertain(user_input) and state.step not in "interviewing":
        bot_messages.append(
            "No worries — take your time. This is just an initial screening."
        )

    step = state.step

    if step == "greeting":
        state.step = next_step(step)
        bot_messages.append(get_bot_message(state))
        return StepResult(state=state, bot_messages=bot_messages)

    if step == "ask_name":
        if not is_valid_name(user_input):
            bot_messages.append("Please enter your **full name** (first and last name).")
            return StepResult(state=state, bot_messages=bot_messages)
        candidate.name = user_input

    elif step == "confirm_resume_data":
        if user_input_clean in {"yes", "y"}:
            c = state.pending_resume_data
            candidate.email = c.get("email") or candidate.email
            candidate.phone = c.get("phone") or candidate.phone
            candidate.location = c.get("location") or candidate.location
            candidate.experience = str(c["experience"]) if c.get("experience") is not None else candidate.experience
            candidate.role = c.get("role") or candidate.role
            candidate.tech_stack = c.get("tech_stack") or candidate.tech_stack
            candidate.education = c.get("education") or candidate.education
            candidate.linkedin = c.get("linkedin") or candidate.linkedin
            candidate.github = c.get("github") or candidate.github

            state.interview_plan = _build_interview_plan(candidate.tech_stack)
            state.interview_index = 0
            state.current_question = ""
            state.qa_history = []
            state.step = "interviewing"
            return StepResult(state=state, bot_messages=bot_messages)
        bot_messages.append(get_bot_message(state))
        return StepResult(state=state, bot_messages=bot_messages)
    
    elif step == "upload_resume":
        bot_messages.append(
        "A resume is required to continue — please use the upload button above."
    )
        return StepResult(state=state, bot_messages=bot_messages)

    elif step == "interviewing":
        if state.current_question:
            state.qa_history.append((state.current_question, user_input))
        state.interview_index += 1
        state.current_question = ""
        if state.interview_index >= len(state.interview_plan):
            state.step = "end"
            bot_messages.append(get_bot_message(state))
        return StepResult(state=state, bot_messages=bot_messages)

    state.step = next_step(step)
    bot_messages.append(get_bot_message(state))
    return StepResult(state=state, bot_messages=bot_messages)