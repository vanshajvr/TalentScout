from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

with engine.begin() as conn:
    for column, ddl in [
        ("judge_scores", "JSON"),
        ("judge_rationale", "TEXT"),
        ("judge_manipulation", "BOOLEAN"),
        ("judge_model", "VARCHAR(80)"),
        ("judge_prompt_sha", "VARCHAR(12)"),
        ("judge_error", "VARCHAR(255)"),
        ("judged_at", "TIMESTAMP"),
        ("override_scores", "JSON"),
        ("override_by", "UUID REFERENCES recruiters(id) ON DELETE SET NULL"),
        ("override_at", "TIMESTAMP"),
    ]:
        conn.execute(text(f"ALTER TABLE mcq_answers ADD COLUMN IF NOT EXISTS {column} {ddl}"))

print("Migration complete: mcq_answers judge_* / override_* columns added.")
