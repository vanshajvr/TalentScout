"""open-text judge scores and recruiter overrides on mcq_answers

Idempotent (IF NOT EXISTS): safe on databases where the old
migrations/migrate_open_text_judge.py script already ran.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

COLUMNS = [
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
]


def upgrade() -> None:
    for column, ddl in COLUMNS:
        op.execute(f"ALTER TABLE mcq_answers ADD COLUMN IF NOT EXISTS {column} {ddl}")


def downgrade() -> None:
    for column, _ in reversed(COLUMNS):
        op.execute(f"ALTER TABLE mcq_answers DROP COLUMN IF EXISTS {column}")
