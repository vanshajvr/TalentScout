from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# Wipes candidate/session data only, for a fresh start on the candidate side.
# Leaves recruiters, organizations, invite_tokens, recruiter_sessions, and
# mcq_questions (the seeded technical question pool) completely untouched —
# your admin/recruiter accounts and org setup stay exactly as they are.
TABLES_TO_WIPE = [
    "candidates", "sessions", "messages", "generated_questions",
    "mcq_assessments", "mcq_answers", "session_logs",
]

with engine.begin() as conn:
    table_list = ", ".join(f'"{t}"' for t in TABLES_TO_WIPE)
    conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))

print(f"Wiped {len(TABLES_TO_WIPE)} candidate/session tables. Recruiters, orgs, invites, and mcq_questions were left untouched.")