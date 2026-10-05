from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

with engine.begin() as conn:
    conn.execute(text("""
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
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_job_openings_org_id ON job_openings (org_id)"))

    conn.execute(text(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS job_id UUID "
        "REFERENCES job_openings(id) ON DELETE SET NULL"
    ))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_candidates_job_id ON candidates (job_id)"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_score INTEGER"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_summary TEXT"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_details JSON"))

print("Migration complete: job_openings table added; candidates.job_id / fit_score / fit_summary / fit_details added.")
