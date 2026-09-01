# TalentScout — AI Hiring Assistant

A full-stack, multi-tenant AI-powered hiring platform. Organizations sign up,
invite recruiters, and run first-round candidate screenings end-to-end:
resume upload and parsing, an adaptive LLM-generated technical + behavioral
interview, and automatic rubric-based scoring — with a recruiter dashboard
and a separate admin dashboard for team and org management.

**Live demo:** https://talentscout-n2bb.onrender.com

---

## Key Features

**Candidate flow**
- Conversational, chat-based screening — resume upload drives the whole flow,
  no multi-step form
- Resume upload (PDF/DOCX) with LLM-based extraction of email, phone,
  location, experience, role, tech stack, education, LinkedIn, and GitHub,
  including data hidden behind PDF hyperlinks (e.g. a "Gmail" link label)
- A single editable confirmation card for all extracted fields, so the
  candidate corrects mistakes in one step instead of retyping everything
- Adaptive interview questions generated live from the candidate's actual
  tech stack and stated experience level — no fixed question bank
- Every answer scored on three dimensions (correctness, reasoning,
  communication) with a one-line justification, not just left as a raw
  transcript for a recruiter to read cold

**Multi-tenant org model**
- Organizations are isolated — one company's recruiters never see another
  company's candidates
- Three-tier access: **admin** (org owner — manages the team, generates
  invites, promotes/demotes recruiters) and **recruiter** (reviews
  candidates, transcripts, and scores within their own org)
- Recruiter signup is gated behind an admin-generated, single-use invite
  code — no open registration
- Each org gets its own candidate-facing screening link

**Recruiter dashboard**
- Overview stats, filterable/sortable candidate table, per-candidate
  interview Q&A + score viewer, per-candidate session logs (step
  transitions and errors), CSV export
- Bulk candidate deletion with cascading cleanup of related records

**Admin dashboard**
- Org-wide stats (team size, total candidates, pending invites)
- Team management: view, promote/demote, and remove recruiters (with
  safeguards against removing or demoting the last admin in an org)
- Invite code generation and an audit trail of who used which code
- Copyable candidate screening link for the org

---

## Architecture

├── main.py # FastAPI entrypoint, mounts routers/static
├── conversation.py # Deterministic state-machine conversation logic
├── deps.py # Shared DB dependency helpers
├── create_tables.py # Fresh-schema creation script
├── migrate_org.py # One-off migration: backfills org/RBAC schema
├── db/
│ ├── database.py # SQLAlchemy session/engine setup
│ └── models.py # Candidate, Session, Message, GeneratedQuestion,
│ # Recruiter, Organization, InviteToken, SessionLog
├── llm/
│ ├── base.py # LLM interface (provider-agnostic)
│ ├── groq_llm.py # Groq API implementation (active in production)
│ └── ollama_llm.py # Local Ollama implementation (offline fallback)
├── prompts/
│ ├── system_prompt.txt
│ ├── next_question_prompt.txt
│ ├── resume_extraction_prompt.txt
│ └── answer_scoring_prompt.txt
├── routers/
│ ├── candidate.py # Session, messaging, resume upload/confirm endpoints
│ ├── recruiter.py # Auth, candidate listing, export, delete, org context
│ └── admin.py # Org signup, team management, invite codes
├── utils/
│ ├── auth.py # Shared token issuance/validation, password hashing
│ ├── schemas.py # Shared Pydantic response models
│ ├── constants.py # Conversation step order, config
│ └── validators.py # Name/email/phone/experience validation
└── static/
├── index.html / app.js / landing.js # Marketing landing page + candidate chat UI
├── login.html / login.js # Role-select page (candidate/recruiter/admin)
├── recruiter.html / recruiter.js # Recruiter dashboard UI
├── admin.html / admin.js # Admin dashboard UI
├── shared.js # Shared frontend helpers (escaping, error formatting)
└── style.css


**Design highlights**
- Deterministic state machine drives the conversation; the LLM is only used
  for resume-field extraction, interview-question generation, and answer
  scoring — never for control flow
- LLM provider is swappable behind a single interface (`BaseLLM`)
- Auth (token issuance, expiry, password hashing, role checks) lives in one
  shared `utils/auth.py` module, imported by both the recruiter and admin
  routers rather than duplicated
- Org isolation is enforced at the query level — every candidate-facing
  endpoint filters by the requesting recruiter's `org_id`, not just hidden
  in the UI

---

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL (Neon)
- **LLM:** Groq API (`openai/gpt-oss-120b`) in production; local Ollama
  supported as an offline fallback
- **Resume parsing:** `pdfplumber` (including PDF hyperlink extraction),
  `python-docx`
- **Frontend:** Vanilla HTML/CSS/JS — no framework, no build step
- **Auth:** PBKDF2-hashed passwords (per-account salt), bearer tokens with
  a 12-hour expiry
- **Deployment:** Render (app), Neon (managed Postgres)

---

## Setup & Run Locally

```bash
git clone https://github.com/vanshajvr/TalentScout.git
cd TalentScout

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example` for the full list):
DATABASE_URL=postgresql://user:password@host:5432/dbname
GROQ_API_KEY=your_groq_api_key


Create the schema:
```bash
python create_tables.py
```

Run the app:
```bash
uvicorn main:app --reload
```

Visit `http://127.0.0.1:8000` for the landing page, `/login` to pick a role,
`/recruiter` for the recruiter dashboard, and `/admin` for the admin
dashboard.

To run against local Ollama instead of Groq, swap the import in
`routers/candidate.py` from `GroqLLM` to `OllamaLLM` and run
`ollama pull llama3` first.

---

## Known Limitations

- Uploaded resumes are stored on local disk — not durable across redeploys
  on platforms with ephemeral filesystems
- Session/auth tokens are stored in-memory and are lost on server restart
  or redeploy — everyone gets logged out when the app redeploys
- No real email or phone verification — identity is self-reported and
  unverified in this demo (an earlier version had OTP verification; it was
  removed after repeated deliverability issues on free-tier hosting, in
  favor of building out the org/RBAC and scoring features instead)
- Schema migrations are hand-written one-off scripts (`migrate_org.py`),
  not a migration framework — acceptable at this project's current size,
  worth revisiting if schema changes become more frequent

---

## Data Privacy

This application stores real candidate and recruiter data — names, emails,
phone numbers, resume contents, and interview transcripts — in Postgres.
It is not an anonymized or in-memory-only demo.

- Recruiter signup requires an admin-issued, single-use invite code — there
  is no open registration
- Candidate data is isolated per organization; recruiters can only see
  candidates within their own org
- Passwords are never stored in plain text (PBKDF2 + per-account salt)
- `.env` and uploaded files are excluded from version control
- **Not yet implemented:** an automatic data retention window, and a
  candidate-initiated deletion path (currently deletion is recruiter/admin
  only, via the dashboard)

## Human-in-the-Loop & Limitations

This tool assists a human recruiter — it generates questions and scores
answers on a rubric, it does not itself reject or auto-disqualify any
candidate. It has not undergone a bias or adverse-impact audit and is a
portfolio/learning project, not a production hiring product. Automated
employment screening is a regulated space in many jurisdictions (e.g. NYC
Local Law 144, the EU AI Act) — any real-world deployment of a tool like
this would need a proper audit first.

---

## Summary

Originally built as a Streamlit AI/ML internship assignment prototype,
rebuilt into a full-stack, multi-tenant application demonstrating:
- Resume parsing and structured LLM extraction
- Rubric-based LLM answer scoring, not just raw transcripts
- Multi-tenant org isolation and role-based access control
- Clean conversational state management independent of the LLM
- Provider-agnostic LLM integration
- A real, deployed product surface — candidate flow, recruiter dashboard,
  and admin dashboard — not just a chatbot demo

  