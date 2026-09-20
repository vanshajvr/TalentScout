from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

with engine.begin() as conn:
    # --- invite_tokens: new audit/expiry/revocation columns ---
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS used_by_name VARCHAR(120)"))
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS used_ip VARCHAR(45)"))
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS used_user_agent VARCHAR(255)"))
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP"))
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP"))
    conn.execute(text("ALTER TABLE invite_tokens ADD COLUMN IF NOT EXISTS revoked_by UUID"))

    # Backfill used_by_name for invites already used, before used_by's FK behavior changes below
    # (once it can go NULL on delete, this join would silently lose the name for anyone removed since).
    conn.execute(text("""
        UPDATE invite_tokens
        SET used_by_name = recruiters.name
        FROM recruiters
        WHERE invite_tokens.used_by = recruiters.id
          AND invite_tokens.used_by_name IS NULL
    """))

    # used_by previously had no ON DELETE behavior (default RESTRICT), which silently blocked
    # deleting ANY recruiter who had ever redeemed an invite — i.e. almost everyone except a
    # founding admin. Switch to SET NULL; used_at/used_by_name above keep the audit trail intact
    # regardless of whether the recruiter row still exists.
    conn.execute(text("ALTER TABLE invite_tokens DROP CONSTRAINT IF EXISTS invite_tokens_used_by_fkey"))
    conn.execute(text("""
        ALTER TABLE invite_tokens
        ADD CONSTRAINT invite_tokens_used_by_fkey
        FOREIGN KEY (used_by) REFERENCES recruiters(id) ON DELETE SET NULL
    """))

    # revoked_by is a new column, so give it the same SET NULL behavior from the start.
    conn.execute(text("ALTER TABLE invite_tokens DROP CONSTRAINT IF EXISTS invite_tokens_revoked_by_fkey"))
    conn.execute(text("""
        ALTER TABLE invite_tokens
        ADD CONSTRAINT invite_tokens_revoked_by_fkey
        FOREIGN KEY (revoked_by) REFERENCES recruiters(id) ON DELETE SET NULL
    """))

    # --- recruiter_sessions: new table, login audit + session-duration tracking combined ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS recruiter_sessions (
            id UUID PRIMARY KEY,
            recruiter_id UUID REFERENCES recruiters(id) ON DELETE SET NULL,
            org_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
            email_attempted VARCHAR(255) NOT NULL,
            success BOOLEAN NOT NULL,
            ip VARCHAR(45),
            user_agent VARCHAR(255),
            token_hash VARCHAR(64),
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP,
            end_reason VARCHAR(20)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_recruiter_sessions_token_hash ON recruiter_sessions (token_hash)"
    ))

print(
    "Migration complete: invite_tokens audit/expiry/revocation columns added, "
    "used_by FK now ON DELETE SET NULL, recruiter_sessions table created."
)