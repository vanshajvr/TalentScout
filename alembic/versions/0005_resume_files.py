"""store uploaded resumes in Postgres instead of local disk

The app's disk is wiped on every Render deploy, which broke resume downloads for
every candidate who applied before the latest deploy.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS resume_files (
            id UUID PRIMARY KEY,
            candidate_id UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            content_type VARCHAR(100) NOT NULL,
            size_bytes INTEGER NOT NULL,
            data BYTEA NOT NULL,
            uploaded_at TIMESTAMP NOT NULL
        )
    """)
    # One file per candidate, enforced by this unique index (matching the model's
    # unique=True, index=True, so `alembic check` sees no drift).
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_resume_files_candidate_id ON resume_files (candidate_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resume_files")
