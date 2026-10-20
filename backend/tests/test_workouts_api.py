"""Workout library endpoints: CRUD, user scoping, duplicate and Garmin push.

Garmin is replaced by ``FakeLibraryGarminClient`` via dependency override;
no real Garmin API calls are made.
"""

import logging
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import create_token, hash_password
from app.db import Base, get_db
from app.garmin.client import GarminClient, LoginResult, get_garmin_client
from app.main import app
from app.models import User
from app.workouts.models import LibraryWorkoutPush
from app.workouts.service import copy_name
from tests.workout_builders import interval_workout, step, workout

PUSH_DATE = "2026-10-21"


class FakeLibraryGarminClient(GarminClient):
    """In-memory Garmin client recording scheduled workout bodies."""

    def __init__(
        self, logged_in: bool = True, needs_mfa: bool = False, fail_upload: bool = False
    ):
        self.logged_in = logged_in
        self.needs_mfa = needs_mfa
        self.fail_upload = fail_upload
        self.uploads: list[tuple[dict, date]] = []

    def login(self, mfa_code: str | None = None) -> LoginResult:
        if self.needs_mfa:
            return LoginResult(needs_mfa=True, message="Enter the MFA code")
        if not self.logged_in:
            return LoginResult(success=False, message="Bad credentials")
        return LoginResult(success=True, message="Logged in")

    def is_logged_in(self) -> bool:
        return self.logged_in and not self.needs_mfa

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        if self.fail_upload:
            raise RuntimeError("Garmin connection error: 500 Internal Server Error")
        self.uploads.append((workout_json, target_date))
        return str(9000 + len(self.uploads))


@pytest.fixture()
def api():
    """Yield (client, session factory, auth headers for the registered user)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    creds = {"email": "caio@example.com", "password": "secret123"}
    token = client.post("/api/auth/register", json=creds).json()["token"]
    yield client, session_factory, {"Authorization": f"Bearer {token}"}
    app.dependency_overrides.clear()


def other_user_headers(session_factory) -> dict[str, str]:
    """Insert a second user directly (registration is closed) and auth as them."""
    with session_factory() as db:
        user = User(email="other@example.com", password_hash=hash_password("x" * 8))
        db.add(user)
        db.commit()
        return {"Authorization": f"Bearer {create_token(user.id)}"}


def use_garmin(fake: FakeLibraryGarminClient | None) -> None:
    app.dependency_overrides[get_garmin_client] = lambda: fake


def create(client: TestClient, headers: dict, payload: dict | None = None) -> dict:
    resp = client.post(
        "/api/workouts", json=payload or interval_workout(), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_requires_auth(api):
    client, _, _ = api
    assert client.get("/api/workouts").status_code == 401


def test_create_returns_full_workout(api):
    client, _, headers = api
    body = create(
        client, headers, workout("Easy", step(end={"type": "time", "seconds": 1800}))
    )
    assert body["name"] == "Easy"
    assert body["description"] == "Track session"
    assert body["steps"][0]["kind"] == "step"
    assert body["estimated_duration_sec"] == 1800
    assert body["estimated_distance_m"] is None
    assert body["pushes"] == []
    assert body["created_at"] and body["updated_at"]


def test_create_invalid_payload_is_422(api):
    client, _, headers = api
    resp = client.post("/api/workouts", json=workout(""), headers=headers)
    assert resp.status_code == 422


def test_list_summaries_newest_updated_first(api):
    client, _, headers = api
    first = create(client, headers, interval_workout("First"))
    create(client, headers, interval_workout("Second"))
    client.put(
        f"/api/workouts/{first['id']}",
        json=interval_workout("First v2"),
        headers=headers,
    )
    rows = client.get("/api/workouts", headers=headers).json()
    assert [r["name"] for r in rows] == ["First v2", "Second"]
    assert rows[0]["step_count"] == 10
    assert set(rows[0]) == {
        "id",
        "name",
        "description",
        "step_count",
        "estimated_duration_sec",
        "estimated_distance_m",
        "updated_at",
    }


def test_get_update_delete_roundtrip(api):
    client, _, headers = api
    wid = create(client, headers)["id"]
    assert client.get(f"/api/workouts/{wid}", headers=headers).json()["id"] == wid
    updated = client.put(
        f"/api/workouts/{wid}", json=workout("Renamed"), headers=headers
    )
    assert updated.json()["name"] == "Renamed"
    assert len(updated.json()["steps"]) == 1
    assert client.delete(f"/api/workouts/{wid}", headers=headers).status_code == 204
    assert client.get(f"/api/workouts/{wid}", headers=headers).status_code == 404


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("put", "", interval_workout()),
        ("delete", "", None),
        ("post", "/duplicate", None),
        ("post", "/push", {"date": PUSH_DATE}),
    ],
)
def test_missing_and_foreign_workouts_are_404(api, method, suffix, body):
    client, session_factory, headers = api
    use_garmin(FakeLibraryGarminClient())
    wid = create(client, headers)["id"]
    other = other_user_headers(session_factory)
    for target_id, hdrs in ((999, headers), (wid, other)):
        resp = client.request(
            method, f"/api/workouts/{target_id}{suffix}", json=body, headers=hdrs
        )
        assert resp.status_code == 404, (method, suffix, target_id)
        assert f"id={target_id}" in resp.json()["detail"]


def test_list_is_scoped_to_user(api):
    client, session_factory, headers = api
    create(client, headers)
    assert (
        client.get("/api/workouts", headers=other_user_headers(session_factory)).json()
        == []
    )


def test_duplicate_copies_steps_with_suffix(api):
    client, _, headers = api
    original = create(client, headers)
    resp = client.post(f"/api/workouts/{original['id']}/duplicate", headers=headers)
    assert resp.status_code == 201
    copy = resp.json()
    assert copy["id"] != original["id"]
    assert copy["name"] == "Intervals (copy)"
    assert copy["steps"] == original["steps"]
    assert copy["pushes"] == []


def test_copy_name_stays_within_limit():
    assert copy_name("Tempo") == "Tempo (copy)"
    long_copy = copy_name("n" * 100)
    assert len(long_copy) == 100 and long_copy.endswith(" (copy)")


def test_push_success_records_each_push(api):
    client, session_factory, headers = api
    fake = FakeLibraryGarminClient()
    use_garmin(fake)
    wid = create(client, headers)["id"]
    first = client.post(
        f"/api/workouts/{wid}/push", json={"date": PUSH_DATE}, headers=headers
    )
    second = client.post(
        f"/api/workouts/{wid}/push", json={"date": PUSH_DATE}, headers=headers
    )
    assert first.status_code == 200
    assert first.json()["date"] == PUSH_DATE
    assert first.json()["garmin_workout_id"] == "9001"
    assert fake.uploads[0][1] == date(2026, 10, 21)
    assert (
        fake.uploads[0][0]["workoutSegments"][0]["workoutSteps"][1]["type"]
        == "RepeatGroupDTO"
    )
    pushes = client.get(f"/api/workouts/{wid}", headers=headers).json()["pushes"]
    assert [p["garmin_workout_id"] for p in pushes] == ["9002", "9001"]
    assert second.json()["garmin_workout_id"] == "9002"


def test_push_upload_failure_is_502_and_logged(api, caplog):
    client, session_factory, headers = api
    use_garmin(FakeLibraryGarminClient(fail_upload=True))
    wid = create(client, headers)["id"]
    with caplog.at_level(logging.WARNING, logger="app.workouts.service"):
        resp = client.post(
            f"/api/workouts/{wid}/push", json={"date": PUSH_DATE}, headers=headers
        )
    assert resp.status_code == 502
    assert "500 Internal Server Error" in resp.json()["detail"]
    record = next(r for r in caplog.records if r.name == "app.workouts.service")
    assert record.dataset == "library_push"
    assert record.library_workout_id == wid
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LibraryWorkoutPush)) == 0


def test_push_without_credentials_is_403(api):
    client, _, headers = api
    use_garmin(None)
    wid = create(client, headers)["id"]
    resp = client.post(
        f"/api/workouts/{wid}/push", json={"date": PUSH_DATE}, headers=headers
    )
    assert resp.status_code == 403
    assert "Garmin credentials not configured" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("fake", "detail_prefix"),
    [
        (FakeLibraryGarminClient(needs_mfa=True), "MFA required"),
        (FakeLibraryGarminClient(logged_in=False), "Garmin login failed"),
    ],
)
def test_push_login_problems_are_401(api, fake, detail_prefix):
    client, _, headers = api
    use_garmin(fake)
    wid = create(client, headers)["id"]
    resp = client.post(
        f"/api/workouts/{wid}/push", json={"date": PUSH_DATE}, headers=headers
    )
    assert resp.status_code == 401
    assert resp.json()["detail"].startswith(detail_prefix)
    assert fake.uploads == []


def test_push_invalid_date_is_422(api):
    client, _, headers = api
    use_garmin(FakeLibraryGarminClient())
    wid = create(client, headers)["id"]
    resp = client.post(
        f"/api/workouts/{wid}/push", json={"date": "21/10/2026"}, headers=headers
    )
    assert resp.status_code == 422


def test_delete_cascades_pushes(api):
    client, session_factory, headers = api
    use_garmin(FakeLibraryGarminClient())
    wid = create(client, headers)["id"]
    client.post(f"/api/workouts/{wid}/push", json={"date": PUSH_DATE}, headers=headers)
    client.delete(f"/api/workouts/{wid}", headers=headers)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LibraryWorkoutPush)) == 0
