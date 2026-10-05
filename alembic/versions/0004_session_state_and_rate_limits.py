"""persisted conversation state, last-activity tracking, DB-backed rate limits

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS conversation_state JSON")
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP")
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_events (
            id UUID PRIMARY KEY,
            key VARCHAR(200) NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rate_limit_events_key ON rate_limit_events (key)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_limit_events")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS last_activity_at")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS conversation_state")
