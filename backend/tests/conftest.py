"""Shared fixtures: in-memory DB override, real-export import."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.ingestion.export_import import import_export
from app.llm.client import get_llm_client
from app.main import app

EXPORT = Path(__file__).resolve().parents[2] / "temp" / "garmin_info"


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests that use the real-export ``imported`` fixture."""
    for item in items:
        if "imported" in getattr(item, "fixturenames", []):
            item.add_marker(pytest.mark.realdata)


@pytest.fixture(autouse=True)
def no_real_llm():
    """Never call a real LLM API during tests unless a fixture/test already injected a fake."""
    if get_llm_client not in app.dependency_overrides:
        app.dependency_overrides[get_llm_client] = lambda: None
        set_by_fixture = True
    else:
        set_by_fixture = False
    yield
    if set_by_fixture:
        app.dependency_overrides.pop(get_llm_client, None)


def make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def imported():
    """Import the real export once; share the session across tests."""
    db = make_session()
    report = import_export(EXPORT, db)
    yield db, report
    db.close()
