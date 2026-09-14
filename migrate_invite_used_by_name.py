from sqlalchemy import text
from db.database import engine

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS used_by_name VARCHAR(120)"))

    # Backfill from the still-live recruiter rows before the FK behavior changes below.
    conn.execute(text("""
        UPDATE invite_tokens
        SET used_by_name = recruiters.name
        FROM recruiters
        WHERE invite_tokens.used_by = recruiters.id
          AND invite_tokens.used_by_name IS NULL
    """))

    # Recruiters could not be deleted at all while this FK had no ON DELETE behavior
    # (default RESTRICT). Switch to SET NULL so removing a recruiter no longer fails,
    # while used_at/used_by_name above keep the audit trail intact regardless.
    conn.execute(text("ALTER TABLE invite_tokens DROP CONSTRAINT IF EXISTS invite_tokens_used_by_fkey"))
    conn.execute(text("""
        ALTER TABLE invite_tokens
        ADD CONSTRAINT invite_tokens_used_by_fkey
        FOREIGN KEY (used_by) REFERENCES recruiters(id) ON DELETE SET NULL
    """))

print("Migration complete: invite_tokens.used_by_name added, used_by FK now ON DELETE SET NULL.")