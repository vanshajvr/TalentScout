from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db.database import engine

# password_salt is only needed for legacy PBKDF2 accounts now — argon2's hash string
# embeds its own salt, so new/upgraded accounts store NULL here. See utils/auth.py's
# verify_password for the dual-scheme verification + lazy upgrade-on-login logic.

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE recruiters ALTER COLUMN password_salt DROP NOT NULL"))

print("Migration complete: recruiters.password_salt is now nullable.")