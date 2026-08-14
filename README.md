# TalentScout — AI Hiring Assistant

A full-stack AI-powered hiring assistant that conducts first-round candidate
screenings end-to-end: resume upload and parsing, identity verification via
email/phone OTP, and an adaptive technical + behavioral interview generated
live by an LLM — plus a recruiter dashboard to review candidates and their
responses.

**Live demo:** https://talentscout-ai-hiring.up.railway.app

---

## Key Features

**Candidate flow**
- Conversational, chat-based screening — no forms
- Resume upload (PDF/DOCX) with LLM-based extraction of email, phone,
  location, experience, role, tech stack, education, LinkedIn, and GitHub, 
  including data hidden behind PDF hyperlinks (e.g. a "Gmail" link label)
- A single editable confirmation card for all extracted fields, so the
  candidate corrects mistakes in one step instead of retyping everything
- Mandatory email + phone verification via one-time codes, independent of
  what the resume claims
- Adaptive technical interview questions generated per technology in the
  candidate's tech stack, scaled to their experience level (fundamentals /
  applied / advanced), plus two behavioral questions
- Recruiter-toned, conversational question phrasing rather than exam-style
  prompts

**Recruiter dashboard**
- Email/password accounts (hashed with salted PBKDF2 — no shared password)
- Overview stats, filterable/sortable candidate table, per-candidate
  interview Q&A viewer, CSV export
- Bulk candidate deletion with cascading cleanup of related records

---

## Architecture

├── main.py # FastAPI app entrypoint, mounts routers/static
├── conversation.py # Pure state-machine conversation logic
├── deps.py # Shared DB dependency helpers
├── create_tables.py # One-off schema creation script
├── db/
│ ├── database.py # SQLAlchemy session/engine setup
│ └── models.py # Candidate, Session, Message, GeneratedQuestion, Recruiter
├── llm/
│ ├── base.py # LLM interface (provider-agnostic)
│ ├── groq_llm.py # Groq API implementation (active in production)
│ └── ollama_llm.py # Local Ollama implementation (offline fallback)
├── prompts/
│ ├── system_prompt.txt
│ ├── next_question_prompt.txt
│ └── resume_extraction_prompt.txt
├── routers/
│ ├── candidate.py # Session, messaging, resume upload/confirm endpoints
│ └── recruiter.py # Auth, candidate listing, export, delete endpoints
├── static/
│ ├── index.html / app.js # Candidate-facing chat UI
│ ├── recruiter.html / .js # Recruiter dashboard UI
│ └── style.css
└── utils/
├── constants.py # Conversation step order, config
└── validators.py # Name/email/phone/experience validation

**Design highlights**
- Deterministic state machine drives the conversation; the LLM is only
  used for resume-field extraction and interview-question generation —
  never for control flow
- LLM provider is swappable behind a single interface (`BaseLLM`); moving
  from local Ollama to Groq's hosted API required changing one import line
- Backend and frontend are fully decoupled — FastAPI + Postgres on the
  backend, plain HTML/CSS/JS on the frontend (no build step, no framework)

---

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL
- **LLM:** Groq API (`llama-3.3-70b-versatile`) in production; local Ollama
  (Llama 3) supported as a fallback
- **Resume parsing:** `pdfplumber` (including PDF hyperlink extraction),
  `python-docx`
- **Frontend:** Vanilla HTML/CSS/JS — no framework
- **Auth:** PBKDF2-hashed recruiter accounts, bearer tokens
- **Email:** SMTP (Gmail) for real OTP delivery
- **Deployment:** Railway (app + managed Postgres)

---

## Setup & Run Locally

```bash
git clone https://github.com/vanshajvr/TalentScout.git
cd TalentScout

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:
DATABASE_URL=postgresql://postgres:devpass@localhost:5432/talentscout
GROQ_API_KEY=your_groq_api_key
SMTP_USER=your_gmail_address
SMTP_PASSWORD=your_gmail_app_password

Start Postgres (Docker) and create the schema:
```bash
docker run --name talentscout-db -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=talentscout -p 5432:5432 -d postgres
python create_tables.py
```

Run the app:
```bash
uvicorn main:app --reload
```

Visit `http://127.0.0.1:8000` for the candidate flow, and
`http://127.0.0.1:8000/recruiter` for the dashboard.

To run against local Ollama instead of Groq, swap the import in
`routers/candidate.py` from `GroqLLM` to `OllamaLLM` and run
`ollama pull llama3` first.

---

## Known Limitations

- Uploaded resumes are stored on local disk — not durable across redeploys
  on platforms with ephemeral filesystems
- Phone OTP is currently simulated (shown directly in the chat) rather
  than sent via real SMS
- In-memory session/token state is lost on server restart

---

## Data Privacy

- No candidate data is used for anything beyond the screening session
- Passwords are never stored in plain text (PBKDF2 + per-account salt)
- `.env` and uploaded files are excluded from version control

---

## Summary

Originally built as a Streamlit AI/ML internship assignment prototype,
rebuilt into a full-stack application demonstrating:
- Resume parsing and structured LLM extraction
- Clean conversational state management independent of the LLM
- Provider-agnostic LLM integration
- A real, deployed recruiter-facing product surface, not just a chatbot demo

