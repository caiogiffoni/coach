"""Full lifecycle integration test against the real exported Garmin data.

Exercises the public API end-to-end with no real Garmin or LLM calls:
register → import → seed → constraints → generate → guard → approve → push → sync.
All external clients are fakes injected via FastAPI dependency overrides.
"""


from datetime import date, datetime, timedelta
from pathlib import Path


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.coaching.plan_models import WeekPlan
from app.db import get_db
from app.garmin.client import GarminClient, LoginResult, get_garmin_client
from app.garmin.models import GarminWorkoutMapping
from app.garmin.push import push_week
from app.ingestion.api_pull import SyncReport
from app.ingestion.models import Activity
from app.llm.client import get_llm_client
from app.main import app
from app.models import User
from app.profile.models import Profile
from conftest import EXPORT

WEEK = date(2026, 5, 11)  # Monday used as the target week.


# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.realdata

class FakePushGarminClient(GarminClient):
    """In-memory Garmin client that records uploaded/scheduled workouts."""

    def __init__(self, logged_in: bool = True):
        self._logged_in = logged_in
        self._counter = 0
        self.scheduled: dict[date, list[dict]] = {}
        self.deleted: list[str] = []
        self.uploaded_json: dict[date, dict] = {}

    def login(self, mfa_code: str | None = None) -> LoginResult:
        if not self._logged_in:
            return LoginResult(success=False, message="Bad credentials")
        return LoginResult(success=True, message="Logged in")

    def logout(self) -> None:
        self._logged_in = False

    def is_logged_in(self) -> bool:
        return self._logged_in

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        if not self.is_logged_in():
            raise RuntimeError("Not logged in")
        self._counter += 1
        workout_id = str(self._counter)
        self.scheduled.setdefault(target_date, []).append(
            {"workoutId": workout_id, "name": workout_json["workoutName"]}
        )
        self.uploaded_json[target_date] = workout_json
        return workout_id

    def delete_workout(self, garmin_workout_id: str) -> None:
        if not self.is_logged_in():
            raise RuntimeError("Not logged in")
        self.deleted.append(garmin_workout_id)
        for d, workouts in self.scheduled.items():
            self.scheduled[d] = [w for w in workouts if w["workoutId"] != garmin_workout_id]

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        if not self.is_logged_in():
            raise RuntimeError("Not logged in")
        return list(self.scheduled.get(target_date, []))

    def get_activities(self, start_date: date, end_date: date) -> list[dict]:
        return []

    def get_daily_wellness(self, start_date: date, end_date: date) -> list[dict]:
        return []

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        return []

    def get_training_readiness(self, start_date: date, end_date: date) -> list[dict]:
        return []

    def get_training_load(self, start_date: date, end_date: date) -> list[dict]:
        return []


class FakeReadGarminClient(GarminClient):
    """Fake client for the sync endpoint; returns one synthetic activity."""

    def __init__(self, as_of: date):
        self.as_of = as_of
        self.calls: list[tuple[str, date, date]] = []

    def login(self, mfa_code: str | None = None) -> LoginResult:
        return LoginResult(success=True, message="Logged in")

    def logout(self) -> None:
        pass

    def is_logged_in(self) -> bool:
        return True

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        return "1"

    def delete_workout(self, garmin_workout_id: str) -> None:
        pass

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        return []

    def get_activities(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_activities", start_date, end_date))
        ts = int(datetime.combine(self.as_of, datetime.min.time()).timestamp() * 1000)
        return [
            {
                "activityId": 9001,
                "name": "E2E Morning Run",
                "activityType": "running",
                "sportType": "running",
                "startTimeGmt": ts,
                "startTimeLocal": ts,
                "duration": 30 * 60 * 1000,
                "distance": 500_000,
                "elevationGain": 1000,
                "avgHr": 150,
                "maxHr": 170,
                "minHr": 100,
                "calories": 300,
                "vO2MaxValue": 50,
                "aerobicTrainingEffect": 2.5,
                "anaerobicTrainingEffect": 0.5,
                "activityTrainingLoad": 120,
                "lapCount": 1,
                "pr": False,
            }
        ]

    def get_daily_wellness(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_daily_wellness", start_date, end_date))
        return [
            {
                "calendarDate": self.as_of.isoformat(),
                "totalSteps": 8000,
                "dailyStepGoal": 10000,
                "totalDistanceMeters": 6000,
                "totalKilocalories": 2200,
                "activeKilocalories": 500,
                "restingHeartRate": 48,
                "minHeartRate": 45,
                "maxHeartRate": 170,
                "highlyActiveSeconds": 1800,
                "activeSeconds": 3600,
                "floorsAscendedInMeters": 10,
            }
        ]

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_hrv", start_date, end_date))
        return []

    def get_training_readiness(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_training_readiness", start_date, end_date))
        return []

    def get_training_load(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_training_load", start_date, end_date))
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def register(client: TestClient) -> dict[str, str]:
    """First-run register; returns Authorization header."""
    creds = {"email": "caio@example.com", "password": "secret123"}
    resp = client.post("/api/auth/register", json=creds)
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def db_user_and_profile(client: TestClient, db) -> tuple[User, Profile]:
    """Fetch the singleton user and profile from the test DB."""
    user = db.scalar(select(User))
    profile = db.scalar(select(Profile))
    assert user is not None
    assert profile is not None
    return user, profile


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_lifecycle(client):
    """End-to-end: register, import, seed, generate, guard, approve, push."""
    fake_garmin = FakePushGarminClient()
    app.dependency_overrides[get_garmin_client] = lambda: fake_garmin
    # No LLM configured → generator uses deterministic fallback.
    app.dependency_overrides[get_llm_client] = lambda: None

    headers = register(client)

    # 1. Import the real GDPR export via the API.
    resp = client.post("/api/ingestion/import", json={"path": str(EXPORT)}, headers=headers)
    assert resp.status_code == 200, resp.text
    import_report = resp.json()
    assert import_report["activities"] > 0 or import_report["daily_wellness"] > 0

    # 2. Seed profile from imported data.
    resp = client.post("/api/profile/seed", headers=headers)
    assert resp.status_code == 200, resp.text
    profile_body = resp.json()
    assert profile_body["goal_mode"] == "health"  # default
    assert profile_body["preferred_days"]  # seeded from run history

    # 3. Constraints endpoint returns valid hard constraints.
    resp = client.get(f"/api/coaching/constraints?week={WEEK}", headers=headers)
    assert resp.status_code == 200, resp.text
    constraints = resp.json()
    assert constraints["week_start"] == str(WEEK)
    assert constraints["weekly_volume_target_km"] > 0
    assert constraints["sessions"]
    allowed_days = set(constraints["allowed_days"])
    for session in constraints["sessions"]:
        assert session["weekday"] in allowed_days
        assert session["distance_km_lo"] <= session["distance_km_hi"]

    # 4. Generate a week (deterministic fallback).
    resp = client.post(
        "/api/coaching/weeks/generate",
        json={"week": str(WEEK), "notes": "e2e test notes"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["week_start"] == str(WEEK)
    assert plan["status"] == "draft"
    assert plan["source"] == "fallback"
    assert plan["notes"] == "e2e test notes"
    assert plan["validation_errors"] == []
    assert len(plan["workouts"]) == len(constraints["sessions"])

    # GET /api/coaching/weeks/{week_start} returns the same structure.
    resp = client.get(f"/api/coaching/weeks/{WEEK}", headers=headers)
    assert resp.status_code == 200, resp.text
    fetched = resp.json()
    assert fetched["id"] == plan["id"]
    assert len(fetched["workouts"]) == len(plan["workouts"])

    # 5. Daily guard for the first workout day returns a recommendation.
    first_workout = plan["workouts"][0]
    workout_date = first_workout["date"]
    resp = client.get(
        f"/api/coaching/guard?week_start={WEEK}&date={workout_date}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    guard = resp.json()
    assert guard["date"] == workout_date
    assert guard["recommendation"] in {"proceed", "swap", "veto"}
    assert guard["current_slot_type"] == first_workout["slot_type"]

    # 6. Approve the week.
    resp = client.post(f"/api/coaching/weeks/{WEEK}/approve", headers=headers)
    assert resp.status_code == 200, resp.text
    approved = resp.json()
    assert approved["status"] == "approved"

    # 7. Push the approved week with the fake Garmin client.
    resp = client.post(f"/api/garmin/push?week_start={WEEK}", headers=headers)
    assert resp.status_code == 200, resp.text
    push_report = resp.json()
    assert push_report["pushed_dates"]
    assert all(isinstance(d, str) for d in push_report["pushed_dates"])

    # 8. Verify DB state: plan pushed, mappings exist, workout statuses updated.
    # We need the DB session behind the fixture to inspect rows directly.
    # The dependency override used by `client` is a factory, not the session
    # itself; reach through the app's override to obtain the same session class.
    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        user, _profile = db_user_and_profile(client, db)
        plan_row = db.scalar(
            select(WeekPlan).where(
                WeekPlan.user_id == user.id, WeekPlan.week_start == WEEK
            )
        )
        assert plan_row is not None
        assert plan_row.status == "pushed"
        assert all(w.status == "pushed" for w in plan_row.workouts)

        mappings = list(
            db.scalars(
                select(GarminWorkoutMapping).where(
                    GarminWorkoutMapping.week_plan_id == plan_row.id
                )
            )
        )
        assert len(mappings) == len(plan_row.workouts)
        mapping_dates = {m.date.isoformat() for m in mappings}
        workout_dates = {w.date.isoformat() for w in plan_row.workouts}
        assert mapping_dates == workout_dates

        # 9. Mapper output for one workout has the expected Garmin JSON shape.
        first_date = min(workout_dates)
        garmin_json = fake_garmin.uploaded_json[date.fromisoformat(first_date)]
        assert garmin_json["workoutName"]
        assert garmin_json["sportType"]["sportTypeKey"] == "running"
        assert garmin_json["workoutSegments"]
        segment = garmin_json["workoutSegments"][0]
        assert segment["sportType"]["sportTypeKey"] == "running"
        assert segment["workoutSteps"]
        for step in segment["workoutSteps"]:
            assert step["type"] == "ExecutableStepDTO"
            assert step["stepType"]["stepTypeKey"]
            assert step["endCondition"]["conditionTypeKey"] == "time"
            assert step["endConditionValue"] > 0
    finally:
        db.close()


def test_sync_with_fake_read_client(client):
    """Sync endpoint does not crash and writes data with a fake read client."""
    headers = register(client)
    as_of = date(2026, 6, 1)
    fake = FakeReadGarminClient(as_of)
    app.dependency_overrides[get_garmin_client] = lambda: fake

    resp = client.post("/api/ingestion/sync", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["activities"] == 1
    assert body["daily_wellness"] == 1
    assert body["newest_date"] == as_of.isoformat()
    assert body["needs_mfa"] is False

    # Verify the activity was actually upserted.
    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        activity = db.scalar(select(Activity).where(Activity.activity_id == 9001))
        assert activity is not None
        assert activity.name == "E2E Morning Run"
    finally:
        db.close()


def test_direct_push_function_sets_status_and_mappings(client):
    """Sanity check that push_week directly marks state as expected."""
    fake = FakePushGarminClient()
    app.dependency_overrides[get_garmin_client] = lambda: fake

    headers = register(client)
    client.post("/api/ingestion/import", json={"path": str(EXPORT)}, headers=headers)
    client.post("/api/profile/seed", headers=headers)
    client.post(
        "/api/coaching/weeks/generate",
        json={"week": str(WEEK)},
        headers=headers,
    )
    client.post(f"/api/coaching/weeks/{WEEK}/approve", headers=headers)

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        user = db.scalar(select(User))
        report = push_week(WEEK, user, db, fake)
        assert report.pushed_dates
        db.refresh(user)
        plan = db.scalar(
            select(WeekPlan).where(
                WeekPlan.user_id == user.id, WeekPlan.week_start == WEEK
            )
        )
        assert plan.status == "pushed"
        assert len(list(plan.workouts)) == len(report.pushed_dates)
    finally:
        db.close()
