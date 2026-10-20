"""Training-state snapshot tests (app/coaching/training_state.py)."""

from datetime import date, datetime, timedelta

from conftest import make_session

from app.coaching.training_state import compute_training_state, iso_monday
from app.ingestion.models import Activity, DailyWellness, Hrv, Sleep, TrainingHistory
from app.profile.models import Profile

MONDAY = date(2026, 6, 1)


def make_profile() -> Profile:
    return Profile(user_id=1, threshold_hr=185, goal_mode="health", preferred_days=[])


def add_run(db, activity_id: int, day: date, km: float, aerobic_te: float | None):
    when = datetime(day.year, day.month, day.day, 8, 0)
    db.add(
        Activity(
            activity_id=activity_id,
            activity_type="running",
            start_time_local=when,
            start_time_gmt=when,
            duration_min=km * 6,
            distance_km=km,
            aerobic_training_effect=aerobic_te,
        )
    )


def test_iso_monday_normalizes_any_weekday():
    assert iso_monday(date(2026, 6, 4)) == MONDAY
    assert iso_monday(date(2026, 6, 7)) == MONDAY
    assert iso_monday(MONDAY) == MONDAY


def test_empty_database_gives_empty_state():
    state = compute_training_state(make_session(), make_profile())
    assert state.as_of is None
    assert state.weekly_volumes == []
    assert state.avg_weekly_km == 0.0
    assert state.days_since_last_run is None
    assert state.resting_hr_latest is None
    assert state.sleep_avg_hours_7d is None


def test_volumes_hard_days_and_recency_anchor_to_latest_data():
    db = make_session()
    add_run(db, 1, MONDAY - timedelta(days=7), 10.0, aerobic_te=4.0)  # hard
    add_run(db, 2, MONDAY - timedelta(days=1), 12.0, aerobic_te=2.0)  # easy Sun
    db.add(DailyWellness(calendar_date=MONDAY + timedelta(days=2), resting_hr=50))
    db.commit()
    state = compute_training_state(db, make_profile())
    assert state.as_of == MONDAY + timedelta(days=2)
    assert state.weekly_volumes[-1].volume_km == 22.0
    assert state.weekly_volumes[-1].complete is True
    assert state.avg_weekly_km == 22.0
    assert state.days_since_last_run == 3
    assert state.days_since_last_hard == 9
    assert (state.resting_hr_latest, state.resting_hr_baseline) == (50, 50.0)


def test_status_prefers_running_history_and_daily_hrv():
    db = make_session()
    db.add(
        TrainingHistory(
            calendar_date=MONDAY, sport="CYCLING", training_status="PEAKING"
        )
    )
    db.add(
        TrainingHistory(
            calendar_date=MONDAY - timedelta(days=3),
            sport="RUNNING",
            training_status="PRODUCTIVE",
        )
    )
    db.add(Hrv(calendar_date=MONDAY, source="sleep", snapshot_time="a", rmssd=20.0))
    db.add(Hrv(calendar_date=MONDAY, source="daily", snapshot_time="b", rmssd=55.0))
    db.add(Sleep(calendar_date=MONDAY, total_sleep_s=7 * 3600, overall_score=80))
    db.commit()
    state = compute_training_state(db, make_profile())
    assert state.training_status == "PRODUCTIVE"
    assert state.hrv_rmssd == 55.0
    assert (state.sleep_avg_hours_7d, state.sleep_avg_score_7d) == (7.0, 80.0)
