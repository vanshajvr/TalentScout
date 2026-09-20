from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE mcq_questions ADD COLUMN IF NOT EXISTS reviewed BOOLEAN DEFAULT FALSE"))

print("Migration complete: mcq_questions.reviewed added (infrastructure only, not yet enforced anywhere).")