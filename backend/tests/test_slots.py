"""Session-skeleton tests (app/coaching/slots.py)."""

from datetime import date, timedelta

from app.coaching.slots import plan_session_slots
from app.coaching.week_policy import WeekPolicy
from app.coaching.zones import compute_zones
from app.profile.models import Profile

MONDAY = date(2026, 6, 1)


def make_policy(weekdays: list[int], **overrides) -> WeekPolicy:
    values: dict = dict(
        days=[MONDAY + timedelta(days=d) for d in weekdays],
        injury_flags=[],
        phase="build",
        weeks_to_race=8,
        cycle="build",
        fatigue_reasons=[],
        target_km=40.0,
        ceiling_km=44.0,
        budget_km=8.0,
        easy_only=False,
        quality_allowed=True,
    )
    values.update(overrides)
    return WeekPolicy(**values)


def zone_data() -> dict:
    return compute_zones(Profile(threshold_hr=185, threshold_pace_sec_per_km=280))


def test_four_days_get_plan_week_roles_and_zone_ranges():
    slots, notes = plan_session_slots(make_policy([0, 2, 4, 6]), zone_data())
    assert [s.type for s in slots] == ["aerobic", "quality", "recovery", "long"]
    assert notes == []
    quality = slots[1]
    assert quality.hr_zone_range == "Z3-Z4"
    assert quality.pace_zone == "threshold"
    assert (quality.distance_km_lo, quality.distance_km_hi) == (7.2, 8.8)
    assert slots[3].distance_km_hi <= 0.30 * 40.0


def test_adjacent_hard_days_downgrade_quality_with_a_note():
    slots, notes = plan_session_slots(make_policy([0, 1]), zone_data())
    assert [s.type for s in slots] == ["aerobic", "long"]
    assert notes == ["Mon quality → aerobic: would be back-to-back with the Tue long"]


def test_easy_only_caps_every_slot_at_z1_z2():
    policy = make_policy(
        [0, 2, 4], easy_only=True, quality_allowed=False, budget_km=0.0
    )
    slots, _ = plan_session_slots(policy, zone_data())
    assert {s.hr_zone_range for s in slots} == {"Z1-Z2"}
    assert slots[-1].rationale.endswith("Capped at Z1-Z2 this week.")


def test_missing_zones_leave_bounds_empty():
    slots, _ = plan_session_slots(make_policy([3]), compute_zones(Profile()))
    assert (slots[0].hr_bpm_lo, slots[0].pace_zone) == (None, None)
