from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# Login/signup now normalize email to lowercase before comparing or storing, but that
# only protects new signups and future login attempts — any recruiter row already
# stored with mixed-case email would still fail to match a normalized (lowercase)
# login attempt, since SQL string equality is case-sensitive by default. This
# normalizes what's already there so the fix is actually complete.
#
# Checks for case-insensitive duplicates first, since normalizing could theoretically
# collide two existing rows that only differ by case (extremely unlikely in practice,
# but worth catching rather than silently violating the unique constraint).

with engine.begin() as conn:
    dupes = conn.execute(text("""
        SELECT LOWER(email), COUNT(*) FROM recruiters GROUP BY LOWER(email) HAVING COUNT(*) > 1
    """)).fetchall()
    if dupes:
        print(f"WARNING: {len(dupes)} email(s) collide case-insensitively across multiple recruiter rows.")
        print("Resolve these manually before re-running this migration.")
        raise SystemExit(1)

    conn.execute(text("UPDATE recruiters SET email = LOWER(email) WHERE email != LOWER(email)"))

print("Migration complete: existing recruiter emails normalized to lowercase.")