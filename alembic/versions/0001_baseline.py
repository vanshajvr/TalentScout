"""baseline: the schema as of commit a0d5083

Everything before Alembic was applied by the one-off scripts that used to live in
migrations/ (see git history). This revision marks that state and changes nothing,
so an existing database can run `alembic upgrade head` without a manual stamp.
A brand-new database is created by `python create_tables.py`, which builds the
current schema and stamps it at head.

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
