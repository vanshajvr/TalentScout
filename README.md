# TalentScout: AI Hiring Assistant

A full-stack, multi-tenant AI-powered hiring platform. Organizations sign up,
invite recruiters, and run first-round candidate screenings end-to-end:
resume upload and parsing, an adaptive MCQ technical + behavioral assessment
with server-authoritative timing and live difficulty adjustment, and a
recruiter dashboard with a separate admin dashboard for team and org
management.

**Live demo:** https://talentscout-n2bb.onrender.com

---

## Key Features

**Candidate flow**
- Conversational, chat-based intake for name/resume, resume upload drives
  the rest of the flow, no multi-step form up front
- Resume upload (PDF/DOCX) with LLM-based extraction of email, phone,
  location, experience, role, tech stack, education, LinkedIn, and GitHub,
  including data hidden behind PDF hyperlinks (e.g. a "Gmail" link label);
  uploads are size-capped, content-validated against their claimed file
  type, and page-limited before extraction
- A single editable confirmation card for all extracted fields, so the
  candidate corrects mistakes in one step instead of retyping everything.
  A duplicate email against an abandoned prior attempt offers a real
  choice — use a different email, or replace the old attempt — instead of
  a silent, permanent lockout
- A 17-question MCQ assessment: 10 technical questions sampled from a
  curated, per-technology/per-difficulty question pool, 5 behavioral
  questions generated fresh per candidate and grounded in their resume, and
  2 open-text prompts
- Technical difficulty adapts live — two correct answers in a row (at the
  same difficulty tier) bump the next question up a level, two incorrect
  drop it down, evaluated on non-overlapping pairs so a streak can't
  double-count
- Server-authoritative per-question timing (60s on technical questions),
  auto-submits on timeout; tab-switch and fullscreen-exit events are logged
  as integrity signals during the assessment, not silently ignored
- A smooth, readable transition into the assessment rather than an instant
  page jump

**Multi-tenant org model**
- Organizations are isolated, one company's recruiters never see another
  company's candidates
- Three-tier access: **admin** (org owner: manages the team, generates
  invites, promotes/demotes recruiters) and **recruiter** (reviews
  candidates, assessment results, and scores within their own org)
- Recruiter signup is gated behind an admin-generated, single-use invite
  code — no open registration
- Each org gets its own candidate-facing screening link

**Recruiter dashboard**
- Overview stats (total, in progress, completed, **abandoned**), a
  filterable/sortable candidate table, per-candidate MCQ results (score,
  difficulty progression, per-question breakdown with correct answers,
  integrity-event counts), per-candidate session logs, CSV export, and
  resume download
- CSV export neutralizes formula injection on every candidate-derived field
- A session with no activity for 48+ hours self-corrects from "in
  progress" to "abandoned" the moment any recruiter loads the dashboard —
  no separate background job
- Bulk candidate deletion with cascading cleanup of related records
  (session, messages, logs, MCQ data)

**Admin dashboard**
- Org-wide stats (team size, total candidates, pending invites)
- Team management: view, promote/demote, and remove recruiters (with
  safeguards against removing or demoting the last admin in an org)
- Invite code generation (with optional expiry) and revocation, and a full
  audit trail of every login attempt and invite redemption — IP, user
  agent, success/failure, session duration
- Copyable candidate screening link for the org

**Security & reliability**
- Passwords hashed with argon2; existing accounts from an earlier PBKDF2
  scheme keep verifying correctly and are transparently upgraded to argon2
  on their next successful login, no forced reset
- Login lockout after repeated failed attempts within a rolling window;
  unauthenticated signup/session-creation endpoints are rate-limited per IP
- Recruiter auth tokens are validated against the database, not an
  in-memory store — sessions survive a restart and work correctly across
  multiple worker processes
- Resume-derived values are never interpolated into raw HTML on the
  candidate confirm card, closing an injection vector
- Runs as a non-root user in Docker

---

## Architecture

```
├── main.py               # FastAPI entrypoint, mounts routers/static
├── conversation.py        # Deterministic state-machine conversation logic
├── deps.py                # Shared DB dependency helpers
├── create_tables.py       # Fresh-schema creation script
├── seed_mcq_pool.py       # Seeds the technical MCQ question pool via LLM
├── migrations/            # One-off migration scripts (run as `python -m migrations.xyz`)
├── db/
│   ├── database.py        # SQLAlchemy session/engine setup
│   └── models.py          # Candidate, Session, Message, GeneratedQuestion,
│                           # Recruiter, Organization, InviteToken, SessionLog,
│                           # RecruiterSession, MCQQuestion, MCQAssessment, MCQAnswer
├── llm/
│   ├── base.py             # LLM interface (provider-agnostic)
│   ├── groq_llm.py         # Groq API implementation (active in production)
│   └── ollama_llm.py       # Local Ollama implementation (offline fallback)
├── prompts/
│   ├── resume_extraction_prompt.txt
│   ├── behavioral_mcq_prompt.txt
│   └── technical_mcq_pool_prompt.txt
├── routers/
│   ├── candidate.py       # Session, messaging, resume upload/confirm endpoints
│   ├── mcq.py              # MCQ assessment: serving, answering, integrity events
│   ├── recruiter.py       # Auth, candidate listing, export, delete, org context
│   └── admin.py           # Org signup, team management, invite codes
├── utils/
│   ├── auth.py             # Token issuance/validation, password hashing
│   ├── rate_limit.py       # In-memory sliding-window rate limiter
│   ├── schemas.py          # Shared Pydantic response models
│   ├── constants.py        # Conversation step order, MCQ config
│   └── validators.py       # Name/email/phone/experience validation
└── static/
    ├── candidate/          # Candidate-facing chat UI + landing page
    ├── mcq/                 # MCQ assessment UI
    ├── recruiter/           # Recruiter dashboard UI
    ├── admin/                # Admin dashboard UI
    ├── login/                # Role-select page (candidate/recruiter/admin)
    ├── shared.js             # Shared frontend helpers (escaping, error formatting)
    └── style.css
```

**Design highlights**
- Deterministic state machine drives the candidate intake conversation; the
  LLM is only used for resume-field extraction and behavioral-question
  generation, never for control flow
- LLM provider is swappable behind a single interface (`BaseLLM`)
- Auth (token issuance, expiry, password hashing, role checks) lives in one
  shared `utils/auth.py` module, imported by both the recruiter and admin
  routers rather than duplicated
- Org isolation is enforced at the query level, every candidate-facing
  endpoint filters by the requesting recruiter's `org_id`, not just hidden
  in the UI
- Technical questions are shuffled per serving (never the pool's own stored
  order) to avoid positional bias in the answer key

---

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL (Neon)
- **LLM:** Groq API (`openai/gpt-oss-120b`) in production; local Ollama
  supported as an offline fallback
- **Resume parsing:** `pdfplumber` (including PDF hyperlink extraction),
  `python-docx`
- **Frontend:** Vanilla HTML/CSS/JS, no framework, no build step
- **Auth:** argon2 password hashing (with a dual-scheme verifier for any
  legacy PBKDF2 accounts), bearer tokens backed by the database with a
  12-hour expiry
- **Deployment:** Render (app, Docker), Neon (managed Postgres)

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
```
DATABASE_URL=postgresql://user:password@host:5432/dbname
GROQ_API_KEY=your_groq_api_key
```


Create the schema:
```bash
python create_tables.py
```

Seed the technical MCQ question pool (requires `GROQ_API_KEY`, safe to
re-run — skips buckets already at their target count):
```bash
python seed_mcq_pool.py
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

- Uploaded resumes are stored on local disk, not durable across redeploys
  on platforms with ephemeral filesystems
- No real email or phone verification, identity is self-reported and
  unverified in this demo (an earlier version had OTP verification; it was
  removed after repeated deliverability issues on free-tier hosting, in
  favor of building out the org/RBAC and assessment features instead)
- Schema migrations are hand-written one-off scripts under `migrations/`
  (run as `python -m migrations.<name>`), not a migration framework,
  acceptable at this project's current size, worth revisiting if schema
  changes become more frequent

---

## Data Privacy

This application stores real candidate and recruiter data: names, emails,
phone numbers, resume contents, and assessment results in Postgres. It is
not an anonymized or in-memory-only demo.

- Recruiter signup requires an admin-issued, single-use invite code; there
  is no open registration
- Candidate data is isolated per organization; recruiters can only see
  candidates within their own org
- Passwords are never stored in plain text (argon2, with legacy PBKDF2
  accounts transparently upgraded on next login)
- `.env` and uploaded files are excluded from version control
- **Not yet implemented:** an automatic data retention window, and a
  candidate-initiated deletion path (currently deletion is recruiter/admin
  only, via the dashboard)

## Human-in-the-Loop & Limitations

This tool assists a human recruiter — it runs the assessment and surfaces
results, it does not itself reject or auto-disqualify any candidate. It has
not undergone a bias or adverse-impact audit and is a portfolio/learning
project, not a production hiring product. Automated employment screening is
a regulated space in many jurisdictions (e.g. NYC Local Law 144, the EU AI
Act), any real-world deployment of a tool like this would need a proper
audit first.

---

## Summary

Originally built as a Streamlit AI/ML internship assignment prototype,
rebuilt into a full-stack, multi-tenant application demonstrating:
- Resume parsing and structured LLM extraction
- An adaptive assessment engine with server-authoritative timing and
  live difficulty adjustment, not just a static quiz
- Multi-tenant org isolation and role-based access control
- Clean conversational state management independent of the LLM
- Provider-agnostic LLM integration
- A systematic security hardening pass: modern password hashing with a
  zero-downtime migration path, rate limiting, injection protections, and
  a database-backed auth/audit trail
- A real, deployed product surface; candidate flow, recruiter dashboard,
  and admin dashboard — not just a chatbot demo