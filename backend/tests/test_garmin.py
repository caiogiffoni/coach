"""Garmin push tests.

All tests use ``FakeGarminClient`` injected via FastAPI dependency override —
no real Garmin API calls are made.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.coaching.plan_models import WeekPlan, Workout
from app.db import Base, get_db
from app.garmin.client import GarminClient, LoginResult, get_garmin_client
from app.garmin.models import GarminWorkoutMapping
from app.garmin.push import push_week
from app.main import app
from app.models import User

WEEK = date(2026, 5, 11)  # Monday


def make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


@pytest.fixture()
def garmin_test():
    """Yield a TestClient, its DB session, and auth headers for a test user."""
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
    client = TestClient(app)

    creds = {"email": "caio@example.com", "password": "secret123"}
    resp = client.post("/api/auth/register", json=creds)
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    db = TestingSession()
    yield client, db, headers

    app.dependency_overrides.clear()
    db.close()


class FakeGarminClient(GarminClient):
    """In-memory Garmin client for tests."""

    def __init__(self, logged_in: bool = True, needs_mfa: bool = False):
        self._logged_in = logged_in
        self._needs_mfa = needs_mfa
        self._pending_mfa = needs_mfa
        self._counter = 0
        self.scheduled: dict[date, list[dict]] = {}
        self.deleted: list[str] = []

    def login(self, mfa_code: str | None = None) -> LoginResult:
        if self._pending_mfa:
            if mfa_code == "123456":
                self._pending_mfa = False
                self._logged_in = True
                return LoginResult(success=True, message="Logged in")
            return LoginResult(
                needs_mfa=True,
                message="Enter the MFA code from your authenticator app",
            )
        if not self._logged_in:
            return LoginResult(success=False, message="Bad credentials")
        return LoginResult(success=True, message="Logged in")

    def logout(self) -> None:
        self._logged_in = False
        self._pending_mfa = False

    def is_logged_in(self) -> bool:
        return self._logged_in and not self._pending_mfa

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        if not self.is_logged_in():
            raise RuntimeError("Not logged in")
        self._counter += 1
        workout_id = str(self._counter)
        self.scheduled.setdefault(target_date, []).append(
            {"workoutId": workout_id, "name": workout_json["workoutName"]}
        )
        return workout_id

    def delete_workout(self, garmin_workout_id: str) -> None:
        if not self.is_logged_in():
            raise RuntimeError("Not logged in")
        self.deleted.append(garmin_workout_id)
        for d, workouts in self.scheduled.items():
            self.scheduled[d] = [
                w for w in workouts if w["workoutId"] != garmin_workout_id
            ]

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        if not self.is_logged_in():
            raise RuntimeError("Not logged in")
        return list(self.scheduled.get(target_date, []))


def make_approved_week(db, user_id: int, week_start: date) -> WeekPlan:
    """Create an approved WeekPlan with two simple running workouts."""
    plan = WeekPlan(
        user_id=user_id,
        week_start=week_start,
        goal_mode="health",
        notes="",
        source="llm",
        status="approved",
    )
    db.add(plan)
    db.flush()

    for i, day_offset in enumerate([0, 2]):
        workout_date = week_start + timedelta(days=day_offset)
        db.add(
            Workout(
                week_plan_id=plan.id,
                date=workout_date,
                name=f"Run {i + 1}",
                sport="running",
                duration_min=45.0,
                description="Easy aerobic run",
                steps=[
                    {
                        "type": "warmup",
                        "duration_min": 10.0,
                        "target_zone": "Z1",
                        "target_pace_min": None,
                        "target_pace_max": None,
                        "target_hr_min": None,
                        "target_hr_max": None,
                    },
                    {
                        "type": "main",
                        "duration_min": 35.0,
                        "target_zone": "Z2",
                        "target_pace_min": None,
                        "target_pace_max": None,
                        "target_hr_min": None,
                        "target_hr_max": None,
                    },
                ],
                slot_type="aerobic",
                status="planned",
            )
        )
    db.commit()
    db.refresh(plan)
    return plan


# ---------------------------------------------------------------------------
# Unit-style push tests (direct DB + fake client)
# ---------------------------------------------------------------------------


def test_push_approved_week_creates_mappings_and_sets_status():
    db = make_session()
    db.add(User(email="caio@example.com", password_hash="x"))
    db.commit()
    user = db.scalar(select(User))
    plan = make_approved_week(db, user.id, WEEK)
    fake = FakeGarminClient()

    report = push_week(WEEK, user, db, fake)

    assert sorted(report.pushed_dates) == [str(WEEK), str(WEEK + timedelta(days=2))]
    assert report.skipped_dates == []
    assert report.errors == []
    assert plan.status == "pushed"
    assert len(plan.workouts) == 2
    assert all(w.status == "pushed" for w in plan.workouts)

    mappings = list(
        db.scalars(
            select(GarminWorkoutMapping).where(
                GarminWorkoutMapping.week_plan_id == plan.id
            )
        )
    )
    assert len(mappings) == 2
    assert {str(m.date) for m in mappings} == {
        str(WEEK),
        str(WEEK + timedelta(days=2)),
    }


def test_repush_deletes_old_workouts_and_replaces_mappings():
    db = make_session()
    db.add(User(email="caio@example.com", password_hash="x"))
    db.commit()
    user = db.scalar(select(User))
    plan = make_approved_week(db, user.id, WEEK)
    fake = FakeGarminClient()

    push_week(WEEK, user, db, fake)
    old_ids = {
        m.garmin_workout_id for m in db.scalars(select(GarminWorkoutMapping))
    }

    # Re-approve is not allowed, so reset status manually for the idempotency test.
    plan.status = "approved"
    for w in plan.workouts:
        w.status = "planned"
    db.commit()

    report = push_week(WEEK, user, db, fake)

    assert sorted(report.pushed_dates) == [str(WEEK), str(WEEK + timedelta(days=2))]
    new_ids = {
        m.garmin_workout_id for m in db.scalars(select(GarminWorkoutMapping))
    }
    assert old_ids.isdisjoint(new_ids)
    assert set(fake.deleted) == old_ids


def test_push_skips_days_with_foreign_workouts():
    db = make_session()
    db.add(User(email="caio@example.com", password_hash="x"))
    db.commit()
    user = db.scalar(select(User))
    plan = make_approved_week(db, user.id, WEEK)
    fake = FakeGarminClient()

    # Pre-existing workout on Wednesday that the app did not create.
    wednesday = WEEK + timedelta(days=2)
    fake.scheduled[wednesday] = [{"workoutId": "9999", "name": "Track Tuesday"}]

    report = push_week(WEEK, user, db, fake)

    assert report.pushed_dates == [str(WEEK)]
    assert len(report.skipped_dates) == 1
    assert "Track Tuesday" in report.skipped_dates[0]["reason"]
    assert plan.status == "pushed"


def test_push_draft_week_raises_409():
    db = make_session()
    db.add(User(email="caio@example.com", password_hash="x"))
    db.commit()
    user = db.scalar(select(User))
    plan = make_approved_week(db, user.id, WEEK)
    plan.status = "draft"
    db.commit()
    fake = FakeGarminClient()

    with pytest.raises(Exception) as exc_info:
        push_week(WEEK, user, db, fake)
    assert exc_info.value.status_code == 409


def test_push_when_not_logged_in_raises_401():
    db = make_session()
    db.add(User(email="caio@example.com", password_hash="x"))
    db.commit()
    user = db.scalar(select(User))
    make_approved_week(db, user.id, WEEK)
    fake = FakeGarminClient(logged_in=False)

    with pytest.raises(Exception) as exc_info:
        push_week(WEEK, user, db, fake)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint tests (dependency override)
# ---------------------------------------------------------------------------


def test_login_mfa_challenge(garmin_test):
    client, db, headers = garmin_test
    fake = FakeGarminClient(needs_mfa=True)
    app.dependency_overrides[get_garmin_client] = lambda: fake

    resp = client.post("/api/garmin/login", json={}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_mfa"] is True
    assert body["success"] is False

    resp = client.post(
        "/api/garmin/login", json={"mfa_code": "123456"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_push_endpoint_approved_week(garmin_test):
    client, db, headers = garmin_test
    fake = FakeGarminClient()
    app.dependency_overrides[get_garmin_client] = lambda: fake

    user = db.scalar(select(User))
    plan = make_approved_week(db, user.id, WEEK)

    resp = client.post(f"/api/garmin/push?week_start={WEEK}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert sorted(body["pushed_dates"]) == [
        str(WEEK),
        str(WEEK + timedelta(days=2)),
    ]

    # Status becomes pushed and buttons hide on next load.
    db.refresh(plan)
    assert plan.status == "pushed"


def test_push_endpoint_missing_credentials(garmin_test):
    client, _db, headers = garmin_test
    app.dependency_overrides[get_garmin_client] = lambda: None

    resp = client.post(f"/api/garmin/push?week_start={WEEK}", headers=headers)
    assert resp.status_code == 403
