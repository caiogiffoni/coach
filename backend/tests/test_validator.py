"""
Validator tests: craft weeks violating each guardrail and expect specific
human-readable errors; a well-formed week (the generator's deterministic
fallback) must come back clean.

Constraints come from the real engine on small synthetic DBs (same helpers
as test_constraints), so the validator is exercised against realistic
SessionSlots rather than hand-built ones.
"""

from datetime import timedelta

from test_constraints import TARGET, build_db, make_profile

from app.coaching.constraints import WeekConstraints, compute_constraints
from app.coaching.generator import fallback_week
from app.coaching.validator import GeneratedWeek, validate_week
from app.ingestion.models import DailyWellness


def health_constraints(**profile_overrides) -> WeekConstraints:
    db = build_db(volumes=[28.0, 30.0])
    return compute_constraints(db, make_profile(**profile_overrides), TARGET)


def race_constraints() -> WeekConstraints:
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TARGET + timedelta(weeks=10),
    )
    return compute_constraints(db, profile, TARGET)


def fatigue_constraints() -> WeekConstraints:
    """Latest RHR +17% over the 30-day median → fatigue veto (all easy)."""
    db = build_db(volumes=[28.0, 30.0])
    anchor = TARGET - timedelta(days=1)
    for i in range(9, 0, -1):
        db.add(DailyWellness(calendar_date=anchor - timedelta(days=i), resting_hr=47))
    db.add(DailyWellness(calendar_date=anchor, resting_hr=55))
    db.commit()
    return compute_constraints(db, make_profile(), TARGET)


def valid_week(c: WeekConstraints) -> GeneratedWeek:
    week = fallback_week(c)
    assert validate_week(week, c) == []  # the fixture itself must be clean
    return week


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_week_has_no_errors():
    assert validate_week(valid_week(health_constraints()), health_constraints()) == []


def test_valid_race_week_with_quality_has_no_errors():
    c = race_constraints()
    assert any(s.type == "quality" for s in c.sessions)
    assert validate_week(valid_week(c), c) == []


# ---------------------------------------------------------------------------
# Day coverage
# ---------------------------------------------------------------------------


def test_workout_on_non_slot_day_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    extra = week.workouts[0].model_copy(
        update={"date": c.week_start + timedelta(days=1)}  # Tuesday: no slot
    )
    week.workouts.append(extra)
    errors = validate_week(week, c)
    assert any("not an allowed training day" in e for e in errors)


def test_missing_slot_day_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    dropped = week.workouts.pop()
    errors = validate_week(week, c)
    assert any(f"{dropped.date}: missing workout" in e for e in errors)


def test_workout_outside_the_week_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    # Move a workout out of the week (and out of its slot): both errors fire.
    week.workouts[0].date = c.week_start - timedelta(days=1)
    errors = validate_week(week, c)
    assert any("outside the week" in e for e in errors)


# ---------------------------------------------------------------------------
# Volume / intensity budget
# ---------------------------------------------------------------------------


def test_quality_distance_over_budget_is_rejected():
    c = race_constraints()
    week = valid_week(c)
    quality_slot = next(s for s in c.sessions if s.type == "quality")
    workout = next(w for w in week.workouts if w.date == quality_slot.date)
    for step in workout.steps:
        step.duration_min *= 2  # ~double the quality distance
    workout.duration_min *= 2
    errors = validate_week(week, c)
    assert any("intensity budget" in e for e in errors)


def test_workout_distance_outside_slot_range_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    workout = week.workouts[0]
    for step in workout.steps:
        step.duration_min *= 3
    errors = validate_week(week, c)
    assert any("outside" in e and "slot range" in e for e in errors)


# ---------------------------------------------------------------------------
# HR / pace bounds
# ---------------------------------------------------------------------------


def test_hr_above_slot_ceiling_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    slot = c.sessions[0]
    assert slot.hr_bpm_hi is not None
    week.workouts[0].steps[1].target_hr_max = slot.hr_bpm_hi + 10
    errors = validate_week(week, c)
    assert any("exceeds the slot ceiling" in e for e in errors)


def test_pace_faster_than_slot_bound_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    slot = c.sessions[0]
    assert slot.pace_lo_sec_per_km is not None
    week.workouts[0].steps[1].target_pace_min = slot.pace_lo_sec_per_km - 20
    errors = validate_week(week, c)
    assert any("faster than the slot allows" in e for e in errors)


def test_easy_bookend_below_hr_floor_is_allowed():
    """A warmup slower/easier than the slot floor is fine (only the
    intensity side of the bounds is enforced on warmup/cooldown)."""
    c = health_constraints()
    week = valid_week(c)
    week.workouts[0].steps[0].target_hr_min = 0  # warmup, very easy
    assert validate_week(week, c) == []


# ---------------------------------------------------------------------------
# Hard-day guardrails (defense in depth, mirroring the constraint engine)
# ---------------------------------------------------------------------------


def test_back_to_back_days_with_injury_flag_are_rejected():
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(injury_history=["IT band syndrome"])
    c = compute_constraints(db, profile, TARGET, days_override=[0, 2, 4])
    week = valid_week(c)
    extra = week.workouts[0].model_copy(
        update={"date": c.week_start + timedelta(days=1)}
    )
    week.workouts.append(extra)
    errors = validate_week(week, c)
    assert any("Back-to-back runs" in e for e in errors)


def test_more_than_two_hard_days_is_rejected():
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TARGET + timedelta(weeks=10),
    )
    c = compute_constraints(db, profile, TARGET, days_override=[0, 1, 2, 4, 6])
    assert sum(1 for s in c.sessions if s.type == "quality") == 2
    week = valid_week(c)
    # LLM smuggles Z5 intensity into an aerobic slot → 3rd hard day.
    aerobic = next(w for w in week.workouts if w.date.weekday() == 0)
    aerobic.steps[1].target_zone = "Z5"
    errors = validate_week(week, c)
    assert any("hard days" in e and "max 2" in e for e in errors)


# ---------------------------------------------------------------------------
# Fatigue veto
# ---------------------------------------------------------------------------


def test_z3_step_during_fatigue_veto_is_rejected():
    c = fatigue_constraints()
    assert c.fatigue_veto is True
    week = valid_week(c)  # fallback respects the veto (all ≤ Z2)
    week.workouts[0].steps[1].target_zone = "Z3"
    errors = validate_week(week, c)
    assert any("fatigue veto" in e for e in errors)


# ---------------------------------------------------------------------------
# Step sanity
# ---------------------------------------------------------------------------


def test_bad_step_type_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    week.workouts[0].steps[0].type = "sprint"
    errors = validate_week(week, c)
    assert any("unknown step type" in e for e in errors)


def test_non_positive_step_duration_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    week.workouts[0].steps[0].duration_min = 0
    errors = validate_week(week, c)
    assert any("duration must be positive" in e for e in errors)


def test_bad_zone_label_is_rejected():
    c = health_constraints()
    week = valid_week(c)
    week.workouts[0].steps[0].target_zone = "Z9"
    errors = validate_week(week, c)
    assert any("unknown zone" in e for e in errors)
