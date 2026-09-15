from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine
from db.models import Base

with engine.begin() as conn:
    # New column on an existing table — create_all() below can't do this, needs a real ALTER.
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS resume_text TEXT"))

# mcq_questions, mcq_assessments, mcq_answers are brand-new tables, not alterations to
# existing ones — create_all() is idempotent (only creates tables that don't exist yet),
# so this is safe to re-run and picks up the new models directly rather than needing
# hand-written CREATE TABLE statements.
Base.metadata.create_all(bind=engine)

print(
    "Migration complete: candidates.resume_text added, "
    "mcq_questions / mcq_assessments / mcq_answers tables created."
)