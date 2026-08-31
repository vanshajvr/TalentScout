from sqlalchemy import text
from db.database import engine
import uuid

DEFAULT_ORG_ID = str(uuid.uuid4())

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS organizations (
            id UUID PRIMARY KEY, name VARCHAR(120), slug VARCHAR(60) UNIQUE, created_at TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS invite_tokens (
            id UUID PRIMARY KEY, org_id UUID, code VARCHAR(64) UNIQUE,
            created_by UUID, used_by UUID, used_at TIMESTAMP, created_at TIMESTAMP
        )
    """))

    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS slug VARCHAR(60) UNIQUE"))

    conn.execute(
        text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, 'Default', 'default', now()) ON CONFLICT (slug) DO NOTHING"),
        {"id": DEFAULT_ORG_ID},
    )
    result = conn.execute(text("SELECT id FROM organizations WHERE slug = 'default'"))
    row = result.fetchone()
    if row is None:
        raise RuntimeError("Failed to create or find the default organization")
    default_org_id = row[0]

    conn.execute(text("ALTER TABLE recruiters ADD COLUMN IF NOT EXISTS org_id UUID"))
    conn.execute(text("ALTER TABLE recruiters ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'recruiter'"))
    conn.execute(text("ALTER TABLE candidates DROP COLUMN IF EXISTS email_verified"))
    conn.execute(text("ALTER TABLE candidates DROP COLUMN IF EXISTS phone_verified"))
    conn.execute(text("UPDATE recruiters SET org_id = :oid WHERE org_id IS NULL"), {"oid": default_org_id})
    conn.execute(text("UPDATE recruiters SET role = 'admin' WHERE role IS NULL"))
    conn.execute(text("ALTER TABLE recruiters ALTER COLUMN org_id SET NOT NULL"))

    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS org_id UUID"))
    conn.execute(text("UPDATE candidates SET org_id = :oid WHERE org_id IS NULL"), {"oid": default_org_id})
    conn.execute(text("ALTER TABLE candidates ALTER COLUMN org_id SET NOT NULL"))

    conn.execute(text("ALTER TABLE candidates DROP CONSTRAINT IF EXISTS candidates_email_key"))
    conn.execute(text("ALTER TABLE candidates ADD CONSTRAINT uq_candidate_org_email UNIQUE (org_id, email)"))

print("Migration complete. Default org id:", default_org_id)