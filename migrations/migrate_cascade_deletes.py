from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# Every one of these FKs previously had no ON DELETE behavior (default RESTRICT), which
# blocked deleting a candidate outright once they had any session detail data — messages,
# generated questions, session logs, or an MCQ assessment/answers. Since these tables are
# pure detail records of a session with no meaning independent of it, CASCADE is the
# correct behavior here (unlike e.g. invite_tokens.used_by, which used SET NULL because
# an invite's usage record still means something after the recruiter who redeemed it is
# gone). This also lets delete_candidates() drop the per-table manual deletion it had to
# hand-maintain, which is exactly the pattern that let mcq_assessments/mcq_answers get
# missed when those tables were added.

CASCADE_FKS = [
    ("sessions", "sessions_candidate_id_fkey", "candidate_id", "candidates(id)"),
    ("generated_questions", "generated_questions_session_id_fkey", "session_id", "sessions(id)"),
    ("messages", "messages_session_id_fkey", "session_id", "sessions(id)"),
    ("session_logs", "session_logs_session_id_fkey", "session_id", "sessions(id)"),
    ("mcq_assessments", "mcq_assessments_session_id_fkey", "session_id", "sessions(id)"),
    ("mcq_answers", "mcq_answers_assessment_id_fkey", "assessment_id", "mcq_assessments(id)"),
]

with engine.begin() as conn:
    for table, constraint, column, references in CASCADE_FKS:
        conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
        conn.execute(text(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY ({column}) REFERENCES {references} ON DELETE CASCADE"
        ))

print("Migration complete: candidate -> session -> detail-table chain now cascades on delete.")