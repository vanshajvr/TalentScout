"""Creates the full current schema on a brand-new, empty database and stamps it at
the latest Alembic revision, so later `alembic upgrade head` runs only apply newer
migrations. For an existing database, use `alembic upgrade head` instead."""

from dotenv import load_dotenv

load_dotenv()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from db.database import engine  # noqa: E402
from db.models import Base  # noqa: E402

Base.metadata.create_all(engine)
command.stamp(Config("alembic.ini"), "head")
print("Tables created and stamped at head:", list(Base.metadata.tables.keys()))
