import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


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


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_registration_open_when_no_users(client):
    assert client.get("/api/auth/status").json() == {"registration_open": True}


def test_register_returns_token_and_closes_registration(client):
    resp = client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    )
    assert resp.status_code == 201
    assert resp.json()["token"]
    assert client.get("/api/auth/status").json() == {"registration_open": False}


def test_second_register_is_forbidden(client):
    client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    )
    resp = client.post(
        "/api/auth/register",
        json={"email": "intruder@example.com", "password": "secret123"},
    )
    assert resp.status_code == 403


def test_register_rejects_short_password(client):
    resp = client.post(
        "/api/auth/register", json={"email": "caio@example.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_login_success(client):
    client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": "caio@example.com", "password": "secret123"}
    )
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_login_wrong_password(client):
    client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": "caio@example.com", "password": "wrongpass"}
    )
    assert resp.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_token(client):
    token = client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    ).json()["token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"email": "caio@example.com"}


def test_me_with_garbage_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
