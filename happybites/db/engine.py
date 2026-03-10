from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from happybites.config import settings


class Base(DeclarativeBase):
    pass


def _configure_sqlite(dbapi_conn, connection_record):
    """Enable WAL mode and foreign keys for SQLite connections."""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


def build_engine(url: str | None = None):
    db_url = url or settings.database_url
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        db_url,
        connect_args=connect_args,
        echo=(settings.environment == "development"),
    )

    if db_url.startswith("sqlite"):
        event.listen(engine, "connect", _configure_sqlite)

    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables. Safe to call multiple times."""
    from happybites.db import models  # noqa: F401 — import to register models

    Base.metadata.create_all(engine)


def get_session():
    """Context manager for a DB session (use in scripts)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
