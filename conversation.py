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
    email_verified: bool = False
    phone_verified: bool = False
    linkedin: str = ""
    github: str = ""


@dataclass
class ConversationState:
    step: str = "greeting"
    candidate: CandidateState = field(default_factory=CandidateState)
    retry: bool = False
    pending_otp: str = ""
    otp_attempts: int = 0
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
    if step == "ask_email":
        return "Thanks. What's your email address?"
    if step == "verify_email":
        return ""  # main.py fills in the mock OTP message
    if step == "ask_phone":
        return "Your phone number, please."
    if step == "verify_phone":
        return ""  # main.py fills in the mock OTP message
    if step == "ask_location":
        return "Where are you currently located?"
    if step == "ask_experience":
        return "How many years of professional experience do you have?"
    if step == "ask_role":
        return "Which position(s) are you applying for?"
    if step == "ask_tech_stack":
        return (
            "Please list your tech stack — programming languages, "
            "frameworks, databases, and tools you are comfortable with."
        )
    if step == "confirm_tech_stack":
        stack = ", ".join(state.candidate.tech_stack)
        return (
            f"You listed the following tech stack:\n\n"
            f"**{stack}**\n\n"
            "Is this correct? (yes / no)\n"
            "You can also add missing technologies."
        )  
    if step == "confirm_education":
        edu = state.pending_resume_data.get("education", "")
        return f"One more thing — your resume shows: **{edu}**. Is that correct? (yes / no)"
    
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

    if seems_uncertain(user_input) and state.step not in ("interviewing", "verify_email", "verify_phone"):
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

    elif step == "ask_email":
        if not is_valid_email(user_input):
            state.retry = True
            bot_messages.append("That doesn't look like a valid email address. Please try again.")
            return StepResult(state=state, bot_messages=bot_messages)
        state.retry = False
        candidate.email = user_input
        state.pending_otp = ""
        state.otp_attempts = 0

    elif step == "ask_phone":
        if not is_valid_phone(user_input):
            bot_messages.append(
                "Please enter a valid phone number. "
                "You may include a country code (e.g., +91XXXXXXXXXX)."
            )
            return StepResult(state=state, bot_messages=bot_messages)
        candidate.phone = user_input
        state.pending_otp = ""
        state.otp_attempts = 0


    elif step == "ask_location":
        candidate.location = user_input

    elif step == "ask_experience":
        if not is_valid_experience(user_input):
            bot_messages.append("Please enter experience in years (e.g., 0, 1.5, 2+).")
            return StepResult(state=state, bot_messages=bot_messages)
        candidate.experience = user_input

    elif step == "ask_role":
        candidate.role = user_input

    elif step == "ask_tech_stack":
        candidate.tech_stack = [t.strip() for t in user_input.split(",") if t.strip()]

    elif step == "confirm_tech_stack":
        if user_input_clean in {"yes", "y"}:
            state.interview_plan = _build_interview_plan(candidate.tech_stack)
            state.interview_index = 0
            state.current_question = ""
            state.qa_history = []
            state.step = "interviewing"
            return StepResult(state=state, bot_messages=bot_messages)
        else:
            additions = [t.strip() for t in user_input.split(",") if t.strip()]
            candidate.tech_stack.extend(additions)
            bot_messages.append(get_bot_message(state))
            return StepResult(state=state, bot_messages=bot_messages)
    
    elif step == "upload_resume":
        bot_messages.append(
        "A resume is required to continue — please use the upload button above."
    )
        return StepResult(state=state, bot_messages=bot_messages)
    
    elif step == "confirm_education":
        if user_input_clean in {"yes", "y"}:
            candidate.education = state.pending_resume_data.get("education", "")
        state.step = "interviewing"
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