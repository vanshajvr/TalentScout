from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# Token expiry previously lived only in the in-memory VALID_TOKENS dict — never
# persisted anywhere, so a restart or a second worker process had no way to know
# when a token should stop working (or even that it existed at all). Now that
# RecruiterSession.token_hash is the sole source of truth for token validity, it
# needs to also carry the expiry itself.

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE recruiter_sessions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP"))

print("Migration complete: recruiter_sessions.expires_at added.")