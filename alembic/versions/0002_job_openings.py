"""job openings and candidate fit scores

Idempotent (IF NOT EXISTS): safe on databases where the old
migrations/migrate_job_openings.py script already ran.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_openings (
            id UUID PRIMARY KEY,
            org_id UUID NOT NULL REFERENCES organizations(id),
            title VARCHAR(120) NOT NULL,
            description TEXT NOT NULL,
            must_have_skills JSON NOT NULL DEFAULT '[]',
            nice_to_have_skills JSON NOT NULL DEFAULT '[]',
            min_experience DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            created_by UUID REFERENCES recruiters(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_openings_org_id ON job_openings (org_id)")
    op.execute(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS job_id UUID "
        "REFERENCES job_openings(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_job_id ON candidates (job_id)")
    op.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_score INTEGER")
    op.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_summary TEXT")
    op.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_details JSON")


def downgrade() -> None:
    for column in ("fit_details", "fit_summary", "fit_score", "job_id"):
        op.execute(f"ALTER TABLE candidates DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS job_openings")
