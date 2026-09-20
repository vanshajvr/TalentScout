from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# created_by previously had no ON DELETE behavior (default RESTRICT), which blocked
# removing any admin who had ever created an invite code. SET NULL (not CASCADE) is
# correct here — an invite's own history (who used it, when) is independent of whether
# its creator still exists, same reasoning as invite_tokens.used_by.

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE invite_tokens DROP CONSTRAINT IF EXISTS invite_tokens_created_by_fkey"))
    conn.execute(text(
        "ALTER TABLE invite_tokens ADD CONSTRAINT invite_tokens_created_by_fkey "
        "FOREIGN KEY (created_by) REFERENCES recruiters(id) ON DELETE SET NULL"
    ))

print("Migration complete: invite_tokens.created_by now ON DELETE SET NULL.")