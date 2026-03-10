"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from happybites.db.engine import Base
from happybites.api.main import app
from happybites.api.deps import get_db
from happybites.db.models import Source

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    # StaticPool forces all threads to share the same in-memory connection.
    # Required because TestClient runs endpoint handlers in a thread pool.
    eng = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    """Per-test DB session with SAVEPOINT isolation.

    Wraps every test in an outer transaction and uses
    join_transaction_mode='create_savepoint' so that any session.commit()
    inside the test (or pipeline code) writes into a nested SAVEPOINT rather
    than the real DB. The outer transaction is always rolled back at teardown,
    giving each test a perfectly clean slate.
    """
    connection = engine.connect()
    trans = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )
    yield session
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture
def fresh_db():
    """Per-test DB session with a brand-new in-memory engine.

    Used for pipeline tests that call db.commit() internally — SAVEPOINT
    isolation cannot roll back real commits on a shared StaticPool connection.
    Each test gets a completely isolated SQLite in-memory database.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        yield session
    Base.metadata.drop_all(eng)


@pytest.fixture
def seeded_db(db):
    """DB with the three default sources pre-inserted."""
    for name, stype in [("dealnews", "rss"), ("reddit", "api"), ("seed", "seed")]:
        if not db.query(Source).filter(Source.name == name).first():
            db.add(
                Source(
                    name=name,
                    type=stype,
                    fetch_interval=7200,
                    is_active=True,
                    consecutive_failures=0,
                    confidence_weight=1.0,
                )
            )
    db.commit()
    return db


@pytest.fixture
def client(seeded_db):
    """FastAPI TestClient wired to the in-memory DB."""

    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
