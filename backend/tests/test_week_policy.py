"""Week-level decision tests (app/coaching/week_policy.py)."""

from datetime import date, timedelta

from app.coaching.constraint_schemas import TrainingState, WeeklyVolume
from app.coaching.week_policy import decide_week_policy, fatigue_reasons
from app.profile.models import Profile

MONDAY = date(2026, 6, 1)


def make_state(**overrides) -> TrainingState:
    values: dict = dict(
        as_of=MONDAY,
        weekly_volumes=[],
        avg_weekly_km=30.0,
        last_complete_week_km=30.0,
        days_since_last_run=1,
        days_since_last_hard=None,
        training_status=None,
        acwr=None,
        acwr_status=None,
        acute_load=None,
        chronic_load=None,
        readiness_score=None,
        readiness_level=None,
        hrv_rmssd=None,
        hrv_status=None,
        hrv_baseline_lo=None,
        hrv_baseline_hi=None,
        resting_hr_latest=None,
        resting_hr_baseline=None,
        sleep_avg_hours_7d=None,
        sleep_avg_score_7d=None,
    )
    values.update(overrides)
    return TrainingState(**values)


def make_profile(**overrides) -> Profile:
    values: dict = dict(
        user_id=1, goal_mode="race", injury_history=[], preferred_days=[0, 2, 4, 5]
    )
    values.update(overrides)
    return Profile(**values)


def rising_weeks() -> list[WeeklyVolume]:
    return [
        WeeklyVolume(
            week_start=MONDAY - timedelta(weeks=4 - i), volume_km=km, complete=True
        )
        for i, km in enumerate([20.0, 22.0, 24.0, 26.0])
    ]


def test_fatigue_reasons_empty_when_fresh():
    assert fatigue_reasons(make_state()) == []


def test_fatigue_reasons_lists_every_signal_in_order():
    state = make_state(
        resting_hr_latest=60,
        resting_hr_baseline=50.0,
        hrv_status="LOW",
        hrv_rmssd=38.0,
        readiness_level="POOR",
        readiness_score=20,
    )
    assert fatigue_reasons(state) == [
        "Resting HR 60 bpm is +20% over the 30-day median (50 bpm)",
        "HRV status LOW (RMSSD 38 ms)",
        "Training readiness POOR (20/100)",
    ]


def test_hrv_below_baseline_floor_is_a_reason():
    state = make_state(hrv_rmssd=30.0, hrv_baseline_lo=40.0)
    assert fatigue_reasons(state) == ["HRV 30 ms below baseline floor (40 ms)"]


def test_build_week_policy_allows_quality_with_20_percent_budget():
    profile = make_profile(goal_race_date=MONDAY + timedelta(weeks=8))
    policy = decide_week_policy(profile, make_state(), MONDAY, None)
    assert policy.cycle == "build"
    assert policy.phase == "build"
    assert policy.days == [MONDAY + timedelta(days=d) for d in (0, 2, 4, 5)]
    assert policy.target_km == 30.0
    assert policy.budget_km == 6.0
    assert policy.quality_allowed is True


def test_deload_policy_is_easy_only_and_explains_itself():
    state = make_state(weekly_volumes=rising_weeks(), last_complete_week_km=26.0)
    policy = decide_week_policy(make_profile(goal_mode="health"), state, MONDAY, None)
    assert policy.cycle == "deload"
    assert policy.target_km == 16.9
    assert (policy.budget_km, policy.easy_only, policy.quality_allowed) == (
        0.0,
        True,
        False,
    )
    assert policy.rationale[0].startswith("Health mode")
    assert policy.rationale[-1] == "Intensity budget 0 km — all sessions easy."


def test_injury_flag_drops_back_to_back_days_and_override_wins():
    profile = make_profile(injury_history=["Left knee pain"])
    policy = decide_week_policy(profile, make_state(), MONDAY, [0, 1, 2])
    assert policy.injury_flags == ["Left knee pain"]
    assert policy.days == [MONDAY, MONDAY + timedelta(days=2)]
    assert "dropped Tuesday" in policy.rationale[0]


def test_empty_preferred_days_fall_back_to_default():
    policy = decide_week_policy(
        make_profile(preferred_days=[]), make_state(), MONDAY, None
    )
    assert [d.weekday() for d in policy.days] == [0, 2, 4, 5]
    assert policy.rationale[0].startswith("No preferred days set")
