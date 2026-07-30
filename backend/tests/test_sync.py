"""Garmin auto-pull sync tests.

All tests use ``FakeGarminClient`` injected via FastAPI dependency override —
no real Garmin API calls are made.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.garmin.client import GarminClient, LoginResult, get_garmin_client
from app.ingestion.api_pull import sync_garmin_data
from app.ingestion.models import (
    Activity,
    DailyWellness,
    Hrv,
    TrainingLoad,
    TrainingReadiness,
)
from app.main import app

TODAY = date(2026, 6, 1)


def make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def sync_test():
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
    """In-memory Garmin client for sync tests."""

    def __init__(
        self,
        logged_in: bool = True,
        needs_mfa: bool = False,
        raise_on: str | None = None,
    ):
        self._logged_in = logged_in
        self._needs_mfa = needs_mfa
        self._pending_mfa = needs_mfa
        self._raise_on = raise_on
        self.calls: list[tuple[str, date, date]] = []

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
        return "1"

    def delete_workout(self, garmin_workout_id: str) -> None:
        pass

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        return []

    def _maybe_raise(self, name: str):
        if self._raise_on == name:
            raise RuntimeError(f"{name} unavailable")

    def get_activities(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_activities", start_date, end_date))
        self._maybe_raise("activities")
        return [
            {
                "activityId": 1001,
                "name": "Morning Run",
                "activityType": "running",
                "sportType": "running",
                "startTimeGmt": int(
                    datetime.combine(TODAY, datetime.min.time()).timestamp() * 1000
                ),
                "startTimeLocal": int(
                    datetime.combine(TODAY, datetime.min.time()).timestamp() * 1000
                ),
                "duration": 30 * 60 * 1000,
                "distance": 500_000,  # 5 km in cm
                "elevationGain": 1000,  # 10 m in cm
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
        self._maybe_raise("daily_wellness")
        return [
            {
                "calendarDate": TODAY.isoformat(),
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
                "allDayStress": {
                    "aggregatorList": [{"type": "TOTAL", "averageStressLevel": 35}]
                },
                "bodyBattery": {
                    "chargedValue": 80,
                    "drainedValue": 60,
                    "bodyBatteryStatList": [
                        {"bodyBatteryStatType": "HIGHEST", "statsValue": 95},
                    ],
                },
            }
        ]

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_hrv", start_date, end_date))
        self._maybe_raise("hrv")
        return [
            {
                "calendarDate": TODAY.isoformat(),
                "hrvSummary": {
                    "metrics": [{"type": "HRV", "value": 55, "status": "BALANCED"}],
                    "baselineLowerLimit": 50,
                    "baselineUpperLimit": 65,
                },
            }
        ]

    def get_training_readiness(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_training_readiness", start_date, end_date))
        self._maybe_raise("training_readiness")
        return [
            {
                "calendarDate": TODAY.isoformat(),
                "score": 75,
                "level": "MODERATE",
                "feedbackShort": "Good to go",
            }
        ]

    def get_training_load(self, start_date: date, end_date: date) -> list[dict]:
        self.calls.append(("get_training_load", start_date, end_date))
        self._maybe_raise("training_load")
        return [
            {
                "calendarDate": TODAY.isoformat(),
                "dailyTrainingLoadAcute": 280,
                "dailyTrainingLoadChronic": 260,
                "dailyAcuteChronicWorkloadRatio": 1.08,
                "acwrStatus": "OPTIMAL",
            }
        ]


# ---------------------------------------------------------------------------
# Unit-style sync tests (direct DB + fake client)
# ---------------------------------------------------------------------------


def test_sync_garmin_data_upserts_all_datasets():
    Session = make_session()
    db = Session()
    fake = FakeGarminClient()

    report = sync_garmin_data(db, fake, days_back=7, as_of=TODAY)

    assert report.activities == 1
    assert report.daily_wellness == 1
    assert report.hrv == 1
    assert report.training_readiness == 1
    assert report.training_load == 1
    assert report.skipped_datasets == []
    assert report.newest_date == TODAY

    activity = db.scalar(select(Activity).where(Activity.activity_id == 1001))
    assert activity is not None
    assert activity.distance_km == pytest.approx(5.0)
    assert activity.duration_min == pytest.approx(30.0)

    wellness = db.scalar(
        select(DailyWellness).where(DailyWellness.calendar_date == TODAY)
    )
    assert wellness is not None
    assert wellness.resting_hr == 48
    assert wellness.total_steps == 8000

    hrv = db.scalar(
        select(Hrv).where(Hrv.calendar_date == TODAY, Hrv.source == "daily")
    )
    assert hrv is not None
    assert hrv.rmssd == 55

    readiness = db.scalar(
        select(TrainingReadiness).where(TrainingReadiness.calendar_date == TODAY)
    )
    assert readiness is not None
    assert readiness.score == 75

    load = db.scalar(select(TrainingLoad).where(TrainingLoad.calendar_date == TODAY))
    assert load is not None
    assert load.acwr == pytest.approx(1.08)

    # Date range is anchored to as_of and looks back days_back.
    assert fake.calls[0] == ("get_activities", TODAY - timedelta(days=7), TODAY)


def test_sync_uses_latest_local_date_as_anchor():
    Session = make_session()
    db = Session()
    yesterday = TODAY - timedelta(days=1)
    db.add(DailyWellness(calendar_date=yesterday, resting_hr=50))
    db.commit()

    fake = FakeGarminClient()
    sync_garmin_data(db, fake, days_back=3)

    # Range should start at yesterday - 3 days, not today - 3 days.
    _, start, end = fake.calls[0]
    assert end == yesterday
    assert start == yesterday - timedelta(days=3)


def test_sync_skips_unavailable_dataset_without_crashing():
    Session = make_session()
    db = Session()
    fake = FakeGarminClient(raise_on="hrv")

    report = sync_garmin_data(db, fake, days_back=7, as_of=TODAY)

    assert report.activities == 1
    assert report.daily_wellness == 1
    assert report.hrv == 0
    assert "hrv" in report.skipped_datasets
    assert report.training_readiness == 1
    assert report.training_load == 1


def test_sync_mfa_short_circuit():
    Session = make_session()
    db = Session()
    fake = FakeGarminClient(needs_mfa=True)

    report = sync_garmin_data(db, fake, days_back=7, as_of=TODAY)

    assert report.needs_mfa is True
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Endpoint tests (dependency override)
# ---------------------------------------------------------------------------


def test_sync_endpoint_requires_auth(sync_test):
    client, _db, _headers = sync_test
    resp = client.post("/api/ingestion/sync", json={})
    assert resp.status_code == 401


def test_sync_endpoint_end_to_end(sync_test):
    client, db, headers = sync_test
    fake = FakeGarminClient()
    app.dependency_overrides[get_garmin_client] = lambda: fake

    resp = client.post("/api/ingestion/sync", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["activities"] == 1
    assert body["daily_wellness"] == 1
    assert body["hrv"] == 1
    assert body["training_readiness"] == 1
    assert body["training_load"] == 1
    assert body["skipped_datasets"] == []
    assert body["newest_date"] == TODAY.isoformat()

    # Data was actually written to the DB.
    assert db.scalar(select(Activity).where(Activity.activity_id == 1001)) is not None


def test_sync_endpoint_missing_credentials(sync_test):
    client, _db, headers = sync_test
    app.dependency_overrides[get_garmin_client] = lambda: None

    resp = client.post("/api/ingestion/sync", json={}, headers=headers)
    assert resp.status_code == 403


def test_sync_endpoint_mfa_challenge(sync_test):
    client, _db, headers = sync_test
    fake = FakeGarminClient(needs_mfa=True)
    app.dependency_overrides[get_garmin_client] = lambda: fake

    resp = client.post("/api/ingestion/sync", json={}, headers=headers)
    assert resp.status_code == 401
    body = resp.json()
    assert body["needs_mfa"] is True


def test_ingestion_status_endpoint(sync_test):
    client, db, headers = sync_test
    db.add(DailyWellness(calendar_date=TODAY, resting_hr=50))
    db.commit()

    resp = client.get("/api/ingestion/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["newest_date"] == TODAY.isoformat()
