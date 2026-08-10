import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLASession

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:devpass@localhost:5432/talentscout",
)

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[SQLASession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()