"""Daily guard tests.

The guard re-runs the constraint engine on the latest synced data and compares
its fresh session allocation to the stored workout.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.coaching.constraints import compute_constraints
from app.coaching.guard import check_day_guard
from app.coaching.plan_models import WeekPlan, Workout
from app.db import Base, get_db
from app.ingestion.models import Activity, DailyWellness
from app.main import app
from app.models import User
from app.profile.models import Profile

TODAY = date(2026, 6, 1)  # Monday
WEEK_START = TODAY


def make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def guard_test():
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


def make_profile(user_id: int) -> Profile:
    return Profile(
        user_id=user_id,
        max_hr=192,
        resting_hr=47,
        threshold_hr=185,
        threshold_pace_sec_per_km=280,
        current_weekly_volume_km=30.0,
        injury_history=[],
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TODAY + timedelta(weeks=10),
        preferred_days=[0, 2, 4, 5],
    )


def add_run(db, when: datetime, km: float, avg_hr: float | None = None):
    db.add(
        Activity(
            activity_id=hash(when.isoformat()) % 1_000_000,
            activity_type="running",
            start_time_local=when,
            start_time_gmt=when,
            duration_min=km * 6,
            distance_km=km,
            avg_hr=avg_hr,
        )
    )


def add_weekly_volume(db, monday: date, km: float):
    add_run(db, datetime(monday.year, monday.month, monday.day, 8, 0), km / 2)
    sunday = monday + timedelta(days=6)
    add_run(db, datetime(sunday.year, sunday.month, sunday.day, 8, 0), km / 2)


def seed_profile_and_data(db, user_id: int):
    """Profile + two recent weeks of running so constraints generate."""
    profile = make_profile(user_id)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    for i, km in enumerate([28.0, 30.0]):
        add_weekly_volume(db, TODAY - timedelta(weeks=2 - i), km)
    db.commit()
    return profile


def make_plan_with_workout(
    db, user_id: int, day_date: date, slot_type: str, steps: list[dict]
) -> tuple[WeekPlan, Workout]:
    plan = WeekPlan(
        user_id=user_id,
        week_start=WEEK_START,
        goal_mode="race",
        notes="",
        source="llm",
        status="draft",
    )
    db.add(plan)
    db.flush()
    workout = Workout(
        week_plan_id=plan.id,
        date=day_date,
        name="Quality session",
        sport="running",
        duration_min=60.0,
        description="",
        steps=steps,
        slot_type=slot_type,
        status="planned",
    )
    db.add(workout)
    db.commit()
    db.refresh(plan)
    db.refresh(workout)
    return plan, workout


# ---------------------------------------------------------------------------
# Unit-style guard tests
# ---------------------------------------------------------------------------


def test_guard_veto_when_rhr_spikes_and_workout_has_intensity():
    Session = make_session()
    db = Session()
    user = User(email="caio@example.com", password_hash="x")
    db.add(user)
    db.commit()
    profile = seed_profile_and_data(db, user.id)

    # RHR baseline 47, latest 55 (+17%) -> fatigue veto.
    for i in range(9, 0, -1):
        db.add(DailyWellness(calendar_date=TODAY - timedelta(days=i), resting_hr=47))
    db.add(DailyWellness(calendar_date=TODAY, resting_hr=55))
    db.commit()

    # Use TODAY (Monday) so the freshest data (TODAY) yields data_age_days == 0.
    plan, _workout = make_plan_with_workout(
        db,
        user.id,
        WEEK_START,
        "quality",
        [{"type": "main", "duration_min": 30, "target_zone": "Z3"}],
    )

    result = check_day_guard(db, profile, WEEK_START, WEEK_START)

    assert result.recommendation == "veto"
    assert any("Resting HR" in r for r in result.fatigue_reasons)
    assert result.current_slot_type == "quality"
    assert result.data_age_days == 0


def test_guard_proceed_when_fresh_constraints_agree():
    Session = make_session()
    db = Session()
    user = User(email="caio@example.com", password_hash="x")
    db.add(user)
    db.commit()
    profile = seed_profile_and_data(db, user.id)

    # Monday is the aerobic slot in a 4-day race week with Mon/Wed/Fri/Sat.
    plan, _workout = make_plan_with_workout(
        db,
        user.id,
        WEEK_START,
        "aerobic",
        [{"type": "main", "duration_min": 40, "target_zone": "Z2"}],
    )

    result = check_day_guard(db, profile, WEEK_START, WEEK_START)

    assert result.recommendation == "proceed"
    assert result.current_slot_type == "aerobic"


def test_guard_swap_when_fresh_constraints_downgrade_quality_day():
    Session = make_session()
    db = Session()
    user = User(email="caio@example.com", password_hash="x")
    db.add(user)
    db.commit()
    profile = make_profile(user.id)
    profile.goal_mode = "health"
    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Need some data so constraints don't fail; health mode has no intensity.
    for i in range(2):
        add_weekly_volume(db, TODAY - timedelta(weeks=2 - i), 30.0)
    db.commit()

    wednesday = TODAY + timedelta(days=2)
    plan, _workout = make_plan_with_workout(
        db,
        user.id,
        wednesday,
        "quality",
        [{"type": "main", "duration_min": 30, "target_zone": "Z3"}],
    )

    result = check_day_guard(db, profile, WEEK_START, wednesday)

    assert result.recommendation == "swap"
    assert result.suggested_slot_type == "aerobic"
    assert result.current_slot_type == "quality"


def test_guard_data_age_days():
    Session = make_session()
    db = Session()
    user = User(email="caio@example.com", password_hash="x")
    db.add(user)
    db.commit()
    profile = seed_profile_and_data(db, user.id)

    # Latest data is two days before the target day.
    latest = TODAY - timedelta(days=2)
    for i in range(2):
        add_weekly_volume(db, latest - timedelta(weeks=2 - i), 30.0)
    db.add(DailyWellness(calendar_date=latest, resting_hr=47))
    db.commit()

    wednesday = TODAY + timedelta(days=2)
    plan, _workout = make_plan_with_workout(
        db,
        user.id,
        wednesday,
        "aerobic",
        [{"type": "main", "duration_min": 40, "target_zone": "Z2"}],
    )

    result = check_day_guard(db, profile, WEEK_START, wednesday)

    assert result.data_age_days == 3  # seed runs push latest to May 31, target is Wed Jun 3
    assert result.recommendation == "proceed"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_guard_endpoint_requires_auth(guard_test):
    client, _db, _headers = guard_test
    resp = client.get(f"/api/coaching/guard?week_start={WEEK_START}&date={WEEK_START}")
    assert resp.status_code == 401


def test_guard_endpoint_veto(guard_test):
    client, db, headers = guard_test
    user = db.scalar(select(User))
    profile = seed_profile_and_data(db, user.id)

    for i in range(9, 0, -1):
        db.add(DailyWellness(calendar_date=TODAY - timedelta(days=i), resting_hr=47))
    db.add(DailyWellness(calendar_date=TODAY, resting_hr=55))
    db.commit()

    wednesday = TODAY + timedelta(days=2)
    make_plan_with_workout(
        db,
        user.id,
        wednesday,
        "quality",
        [{"type": "main", "duration_min": 30, "target_zone": "Z3"}],
    )

    resp = client.get(
        f"/api/coaching/guard?week_start={WEEK_START}&date={wednesday}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recommendation"] == "veto"
    assert body["current_slot_type"] == "quality"


def test_guard_endpoint_404_without_plan(guard_test):
    client, db, headers = guard_test
    user = db.scalar(select(User))
    seed_profile_and_data(db, user.id)

    resp = client.get(
        f"/api/coaching/guard?week_start={WEEK_START}&date={WEEK_START}",
        headers=headers,
    )
    assert resp.status_code == 404


def test_guard_endpoint_404_without_workout_for_date(guard_test):
    client, db, headers = guard_test
    user = db.scalar(select(User))
    seed_profile_and_data(db, user.id)
    # Plan exists but no workout on the requested date.
    plan = WeekPlan(
        user_id=user.id,
        week_start=WEEK_START,
        goal_mode="race",
        notes="",
        source="llm",
        status="draft",
    )
    db.add(plan)
    db.commit()

    resp = client.get(
        f"/api/coaching/guard?week_start={WEEK_START}&date={WEEK_START}",
        headers=headers,
    )
    assert resp.status_code == 404
