from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# Without these, a double-click or two open tabs on the same session could each pass a
# "does this exist yet?" check before either commits, resulting in either two
# MCQAssessment rows for one session, or two MCQAnswer rows at the same question_index.
# The application now catches the resulting IntegrityError and falls back to reading
# whichever row actually won the race (see routers/mcq.py).

with engine.begin() as conn:
    dup_assessments = conn.execute(text(
        "SELECT session_id, COUNT(*) FROM mcq_assessments GROUP BY session_id HAVING COUNT(*) > 1"
    )).fetchall()
    if dup_assessments:
        print(f"WARNING: {len(dup_assessments)} session(s) already have duplicate mcq_assessments rows.")
        print("Resolve these manually (keep one, delete the rest) before re-running this migration.")
        raise SystemExit(1)

    dup_answers = conn.execute(text(
        "SELECT assessment_id, question_index, COUNT(*) FROM mcq_answers "
        "GROUP BY assessment_id, question_index HAVING COUNT(*) > 1"
    )).fetchall()
    if dup_answers:
        print(f"WARNING: {len(dup_answers)} (assessment, question_index) pair(s) already have duplicate mcq_answers rows.")
        print("Resolve these manually (keep one, delete the rest) before re-running this migration.")
        raise SystemExit(1)

    conn.execute(text("ALTER TABLE mcq_assessments DROP CONSTRAINT IF EXISTS uq_mcq_assessment_session"))
    conn.execute(text(
        "ALTER TABLE mcq_assessments ADD CONSTRAINT uq_mcq_assessment_session "
        "UNIQUE (session_id)"
    ))
    conn.execute(text("ALTER TABLE mcq_answers DROP CONSTRAINT IF EXISTS uq_mcq_answer_assessment_question"))
    conn.execute(text(
        "ALTER TABLE mcq_answers ADD CONSTRAINT uq_mcq_answer_assessment_question "
        "UNIQUE (assessment_id, question_index)"
    ))

print("Migration complete: unique constraints added to mcq_assessments and mcq_answers.")