import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLASession

# The only Postgres driver installed is psycopg 3 (see requirements.txt). Plain
# "postgresql://" would make SQLAlchemy reach for psycopg2 instead, and hosts hand out
# every variant ("postgres://", "postgresql+psycopg2://", "postgresql+psycopg://"),
# so the scheme is pinned here rather than trusting whatever was pasted into the env.
_POSTGRES_SCHEMES = ("postgres://", "postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://")


def _with_psycopg3_driver(url: str) -> str:
    for scheme in _POSTGRES_SCHEMES:
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme):]
    return url


DATABASE_URL = _with_psycopg3_driver(os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:devpass@localhost:5432/talentscout",
))

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[SQLASession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()