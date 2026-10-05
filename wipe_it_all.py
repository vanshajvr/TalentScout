"""
Wipes candidate/session data only, for a fresh start on the candidate side.
Leaves recruiters, organizations, invite_tokens, recruiter_sessions, job_openings and
mcq_questions (the seeded technical question pool) untouched.

DATABASE_URL usually comes from .env — which may well point at production. So this
refuses any non-local database unless you pass --allow-remote AND retype the
database name when asked.

    python wipe_it_all.py                  # local database only
    python wipe_it_all.py --allow-remote   # anything else, with confirmation
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402

TABLES_TO_WIPE = [
    "candidates", "sessions", "messages", "generated_questions",
    "mcq_assessments", "mcq_answers", "session_logs",
]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}

host = engine.url.host or "localhost"
database = engine.url.database
print(f"Target: {database} on {host}")

if host not in LOCAL_HOSTS:
    if "--allow-remote" not in sys.argv:
        sys.exit(f"Refusing: {host} isn't a local database. Re-run with --allow-remote if you really mean it.")
    typed = input(f"This permanently deletes every candidate in '{database}' on {host}. Type the database name to confirm: ")
    if typed.strip() != database:
        sys.exit("Confirmation didn't match — nothing was deleted.")

with engine.begin() as conn:
    table_list = ", ".join(f'"{t}"' for t in TABLES_TO_WIPE)
    conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))

print(f"Wiped {len(TABLES_TO_WIPE)} candidate/session tables. Recruiters, orgs, invites, jobs and mcq_questions were left untouched.")
