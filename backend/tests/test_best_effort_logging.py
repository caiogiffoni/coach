"""Best-effort failure paths must keep going *and* emit structured logs.

Uses named fake Garmin clients (no real API calls) and ``caplog`` to assert
on the ``extra={...}`` fields attached to each warning.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.coaching.plan_models import WeekPlan, Workout
from app.db import Base
from app.garmin.client import GarminClient, LoginResult
from app.garmin.models import GarminWorkoutMapping
from app.garmin.push import push_week
from app.ingestion.api_pull import sync_garmin_data
from app.models import User

AS_OF = date(2026, 6, 1)
WEEK = date(2026, 5, 11)  # Monday


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


class QuietGarminClient(GarminClient):
    """Logged-in fake that returns no data and accepts every write."""

    def __init__(self) -> None:
        self._counter = 0
        self.deleted: list[str] = []

    def login(self, mfa_code: str | None = None) -> LoginResult:
        return LoginResult(success=True, message="Logged in")

    def logout(self) -> None:
        pass

    def is_logged_in(self) -> bool:
        return True

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        self._counter += 1
        return str(self._counter)

    def delete_workout(self, garmin_workout_id: str) -> None:
        self.deleted.append(garmin_workout_id)

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        return []

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


class HrvOutageGarminClient(QuietGarminClient):
    """HRV endpoint is down; every other dataset works."""

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        raise RuntimeError("hrv endpoint 503")


class ScheduleRejectingGarminClient(QuietGarminClient):
    """Garmin rejects uploads for one specific date."""

    def __init__(self, reject_date: date) -> None:
        super().__init__()
        self.reject_date = reject_date

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        if target_date == self.reject_date:
            raise RuntimeError("upload rejected 500")
        return super().schedule_workout(workout_json, target_date)


class DeleteRejectingGarminClient(QuietGarminClient):
    """Garmin refuses to delete previously uploaded workouts."""

    def delete_workout(self, garmin_workout_id: str) -> None:
        raise RuntimeError(f"cannot delete {garmin_workout_id}")


def make_user(db: Session) -> User:
    user = User(email="caio@example.com", password_hash="x")
    db.add(user)
    db.commit()
    return user


def make_approved_plan(db: Session, user: User) -> WeekPlan:
    plan = WeekPlan(
        user_id=user.id,
        week_start=WEEK,
        goal_mode="health",
        notes="",
        source="llm",
        status="approved",
    )
    db.add(plan)
    db.flush()
    for offset in (0, 2):
        db.add(
            Workout(
                week_plan_id=plan.id,
                date=WEEK + timedelta(days=offset),
                name=f"Run {offset}",
                sport="running",
                duration_min=30.0,
                description="Easy run",
                steps=[{"type": "main", "duration_min": 30.0, "target_zone": "Z2"}],
                slot_type="aerobic",
                status="planned",
            )
        )
    db.commit()
    db.refresh(plan)
    return plan


def records_with(caplog, **fields) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if all(getattr(r, k, None) == v for k, v in fields.items())
    ]


def test_sync_hrv_failure_is_skipped_and_logged(caplog):
    db = make_db()
    caplog.set_level(logging.WARNING, logger="app.ingestion.api_pull")

    report = sync_garmin_data(db, HrvOutageGarminClient(), as_of=AS_OF, days_back=7)

    assert report.skipped_datasets == ["hrv"]
    (record,) = records_with(caplog, dataset="hrv")
    assert record.levelno == logging.WARNING
    assert "hrv endpoint 503" in record.error
    assert record.start_date == (AS_OF - timedelta(days=7)).isoformat()
    assert record.end_date == AS_OF.isoformat()


def test_push_upload_failure_is_reported_logged_and_others_still_push(caplog):
    db = make_db()
    user = make_user(db)
    plan = make_approved_plan(db, user)
    bad_day = WEEK + timedelta(days=2)
    caplog.set_level(logging.WARNING, logger="app.garmin.push")

    report = push_week(
        WEEK, user, db, ScheduleRejectingGarminClient(reject_date=bad_day)
    )

    assert report.pushed_dates == [WEEK.isoformat()]
    assert report.errors == [f"{bad_day.isoformat()}: upload rejected 500"]
    (record,) = records_with(caplog, dataset="push_workout")
    assert record.date == bad_day.isoformat()
    assert record.week_plan_id == plan.id
    assert "upload rejected 500" in record.error


def test_push_delete_failure_still_replaces_mapping_and_logs(caplog):
    db = make_db()
    user = make_user(db)
    plan = make_approved_plan(db, user)
    db.add(
        GarminWorkoutMapping(week_plan_id=plan.id, date=WEEK, garmin_workout_id="old")
    )
    db.commit()
    caplog.set_level(logging.WARNING, logger="app.garmin.push")

    report = push_week(WEEK, user, db, DeleteRejectingGarminClient())

    assert sorted(report.pushed_dates) == [
        WEEK.isoformat(),
        (WEEK + timedelta(days=2)).isoformat(),
    ]
    assert report.errors == ["Could not delete previous workout old: cannot delete old"]
    (record,) = records_with(caplog, dataset="delete_workout")
    assert record.garmin_workout_id == "old"
    assert record.date == WEEK.isoformat()
