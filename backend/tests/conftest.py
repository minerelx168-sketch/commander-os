"""Shared fixtures — sqlite in-memory DB + mock settings."""
import os

os.environ.update(
    DATABASE_URL="sqlite://",
    LLM_MOCK="1",
    TELEGRAM_MOCK="1",
    META_AGENT_MOCK="1",
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.models  # noqa: F401 — populate Base.metadata before create_all
from app.database import Base


@pytest.fixture(autouse=True)
def _isolate_deliverables(tmp_path, monkeypatch):
    """Never let tests write briefs into the real deliverables dir."""
    from app.services import deliverable

    monkeypatch.setattr(deliverable, "DELIVERABLES_DIR", tmp_path / "deliverables")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    # patch global sessionmaker/engine so app code uses the test DB
    database._engine = engine
    database._SessionLocal = TestSession

    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c
