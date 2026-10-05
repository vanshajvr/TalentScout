from logging.config import fileConfig

from dotenv import load_dotenv

load_dotenv()

from alembic import context  # noqa: E402

from db.database import engine  # noqa: E402  (DATABASE_URL, already normalized to psycopg 3)
from db.models import Base  # noqa: E402

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=engine.url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
