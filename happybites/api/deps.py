"""FastAPI dependency: yields a DB session per request."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from happybites.db.engine import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
