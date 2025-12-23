import streamlit as st
from llm.ollama_llm import OllamaLLM
from utils.constants import STEPS, EXIT_KEYWORDS
from utils.validators import (
    is_valid_name,
    is_valid_email,
    is_valid_phone,
    is_valid_experience,
)

llm = OllamaLLM()

if "step" not in st.session_state:
    st.session_state.step = "greeting"

if "candidate" not in st.session_state:
    st.session_state.candidate = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "experience": "",
        "role": "",
        "tech_stack": []
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

if "questions_generated" not in st.session_state:
    st.session_state.questions_generated = False

with st.sidebar:
    st.header("📋 Candidate Summary")

    c = st.session_state.candidate

    if c["name"]:
        st.write(f"**Name:** {c['name']}")
    if c["email"]:
        st.write(f"**Email:** {c['email']}")
    if c["phone"]:
        st.write(f"**Phone:** {c['phone']}")
    if c["location"]:
        st.write(f"**Location:** {c['location']}")
    if c["experience"]:
        st.write(f"**Experience:** {c['experience']} years")
    if c["role"]:
        st.write(f"**Role:** {c['role']}")
    if c["tech_stack"]:
        st.write("**Tech Stack:**")
        for tech in c["tech_stack"]:
            st.write(f"- {tech}")

def load_prompt(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def next_step(current_step: str) -> str:
    idx = STEPS.index(current_step)
    return STEPS[min(idx + 1, len(STEPS) - 1)]


def get_bot_message(step: str) -> str:
    if step == "greeting":
        return (
            "Hello! 👋 I’m TalentScout’s Hiring Assistant. "
            "I’ll ask you a few questions for initial screening. "
            "You can type **exit** anytime to end the conversation."
        )

    if step == "ask_name":
        return "Let’s begin. What’s your full name?"

    if step == "ask_email":
        if st.session_state.retry:
            return "What’s your email address?"
        return "Thanks. What’s your email address?"

    if step == "ask_phone":
        return "Your phone number, please."

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
        stack = ", ".join(st.session_state.candidate["tech_stack"])
        return (
            f"You listed the following tech stack:\n\n"
            f"**{stack}**\n\n"
            "Is this correct? (yes / no)\n"
            "You can also add missing technologies."
        )

    if step == "generate_questions":
        return ""

    if step == "end":
        return (
            "Thank you for your time. 🙏 "
            "Our team will review your responses and get back to you soon. "
            "Have a great day!"
        )

    return ""

def seems_uncertain(text: str) -> bool:
    low_confidence_phrases = {
        "idk", "not sure", "maybe", "dont know", "don't know", "unsure"
    }
    return any(p in text.lower() for p in low_confidence_phrases)


def handle_user_input(user_input: str):
    user_input_clean = user_input.strip().lower()

  
    if user_input_clean in EXIT_KEYWORDS:
        st.session_state.step = "end"
        return
    
    if seems_uncertain(user_input):
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    "No worries — take your time. "
                    "This is just an initial screening."
                )
            }
        )


    step = st.session_state.step
    candidate = st.session_state.candidate

    if step == "greeting":
        st.session_state.step = "ask_name"
        return
    

    if step == "ask_name":
        if not is_valid_name(user_input):
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "Please enter your **full name** (first and last name)."
                }
            )
            return
        candidate["name"] = user_input

    elif step == "ask_email":
        if not is_valid_email(user_input):
            st.session_state.retry = True
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "That doesn’t look like a valid email address. Please try again."
                }
            )
            return

        st.session_state.retry = False
        candidate["email"] = user_input


    elif step == "ask_phone":
        if not is_valid_phone(user_input):
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "Please enter a valid phone number. "
                        "You may include a country code (e.g., +91XXXXXXXXXX)."
                    )
                }
            )
            return
        candidate["phone"] = user_input

    elif step == "ask_location":
        candidate["location"] = user_input

    elif step == "ask_experience":
        if not is_valid_experience(user_input):
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "Please enter experience in years (e.g., 0, 1.5, 2+)."
                }
            )
            return
        candidate["experience"] = user_input

    elif step == "ask_role":
        candidate["role"] = user_input

    elif step == "ask_tech_stack":
        candidate["tech_stack"] = [
            t.strip() for t in user_input.split(",") if t.strip()
        ]

    elif step == "confirm_tech_stack":
        if user_input_clean in {"yes", "y"}:
            st.session_state.step = "generate_questions"
            return
        else:
            additions = [
                t.strip() for t in user_input.split(",") if t.strip()
            ]
            candidate["tech_stack"].extend(additions)
            
            return


    st.session_state.step = next_step(step)

st.title("TalentScout – Hiring Assistant")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Type your response here...")

if (
    st.session_state.step == "generate_questions"
    and not st.session_state.questions_generated
):
    prompt_template = load_prompt("prompts/tech_questions_prompt.txt")

    filled_prompt = prompt_template.format(
        role=st.session_state.candidate["role"],
        experience=st.session_state.candidate["experience"],
        tech_stack=", ".join(st.session_state.candidate["tech_stack"])
    )

    with st.spinner("Generating technical questions..."):
        questions = llm.generate(filled_prompt)

    st.session_state.messages.append(
        {"role": "assistant", "content": questions}
    )

    st.session_state.questions_generated = True
    st.session_state.step = "end"
    st.rerun()

if user_input:
    st.session_state.messages.append(
        {"role": "user", "content": user_input}
    )

    handle_user_input(user_input)

    bot_reply = get_bot_message(st.session_state.step)

    st.session_state.messages.append(
        {"role": "assistant", "content": bot_reply}
    )

    st.rerun()

if not st.session_state.messages:
    st.session_state.messages.append(
        {"role": "assistant", "content": get_bot_message("greeting")}
    )
if "retry" not in st.session_state:
    st.session_state.retry = False

