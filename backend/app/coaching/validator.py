"""
Week validator — schema + guardrail checks on a generated week (PLAN.md
build-order step 5, "LLM output never reaches Garmin without passing the
validator").

`validate_week(week, constraints)` returns a list of human-readable errors;
an empty list means the week may be stored/shown. The error list is also
fed back into the generator's re-prompt loop, so messages are written for
the LLM as much as for the user.

The Pydantic models below define the LLM output contract itself. They live
here (not in generator.py) so both generator and validator share one
definition without a circular import. Field types are deliberately loose
(`str` for step type / zone, no positive-duration constraint): bad values
must survive parsing so the validator can report them as readable errors
instead of an opaque 500-style ValidationError.

Defense in depth: the hard-day / adjacency / fatigue checks mirror rules
the constraint engine already enforces, so a hostile or confused LLM output
is caught even when the skeleton it was given was safe.
"""

from datetime import date, timedelta

from pydantic import BaseModel

from .constraints import SessionSlot, WeekConstraints

STEP_TYPES = ("warmup", "main", "interval", "recovery", "cooldown", "rest")
ZONES = ("Z1", "Z2", "Z3", "Z4", "Z5")
HARD_ZONES = ("Z3", "Z4", "Z5")

# Per-workout distance tolerance around the slot range, plus a small
# absolute slack for float sums (derived distances come from durations
# rounded to 0.1 min, so a quality workout sized exactly at the budget
# can land a few hundredths of a km over).
DISTANCE_TOLERANCE = 0.10
SUM_TOLERANCE_KM = 0.05

# Steps the LLM may legitimately make easier/slower than the slot bounds
# (a warmup below the HR floor or a cooldown slower than the pace ceiling
# is fine — going *harder* than the bounds never is).
_EASY_BOOKENDS = ("warmup", "cooldown")


class WorkoutStep(BaseModel):
    type: str  # validated against STEP_TYPES (kept as str — see docstring)
    duration_min: float
    target_zone: str | None = None  # validated against ZONES when present
    target_pace_min: int | None = None  # faster bound, sec/km
    target_pace_max: int | None = None  # slower bound, sec/km
    target_hr_min: int | None = None  # bpm
    target_hr_max: int | None = None  # bpm


class GeneratedWorkout(BaseModel):
    name: str
    date: date
    sport: str = "running"
    duration_min: float
    description: str = ""
    steps: list[WorkoutStep]


class GeneratedWeek(BaseModel):
    workouts: list[GeneratedWorkout]


def _step_distance_km(step: WorkoutStep, slot: SessionSlot) -> float | None:
    """
    Derive a step's distance from its duration and pace targets (midpoint
    of the target range; slot pace bounds as fallback). None when no pace
    information exists at all — the distance checks are then skipped.
    """
    if step.target_pace_min and step.target_pace_max:
        pace = (step.target_pace_min + step.target_pace_max) / 2
    elif slot.pace_lo_sec_per_km and slot.pace_hi_sec_per_km:
        pace = (slot.pace_lo_sec_per_km + slot.pace_hi_sec_per_km) / 2
    else:
        return None
    return step.duration_min * 60 / pace


def _workout_distance_km(workout: GeneratedWorkout, slot: SessionSlot) -> float | None:
    parts = [_step_distance_km(s, slot) for s in workout.steps]
    known = [p for p in parts if p is not None]
    return sum(known) if known else None


def _check_step_schema(
    step: WorkoutStep, label: str, constraints: WeekConstraints
) -> list[str]:
    """Durations, step-type / zone enums and the fatigue-veto zone cap."""
    errors = []
    if step.duration_min <= 0:
        errors.append(f"{label}: duration must be positive")
    if step.type not in STEP_TYPES:
        errors.append(
            f"{label}: unknown step type {step.type!r} "
            f"(allowed: {', '.join(STEP_TYPES)})"
        )
    if step.target_zone is not None and step.target_zone not in ZONES:
        errors.append(f"{label}: unknown zone {step.target_zone!r} (Z1-Z5)")
    if constraints.fatigue_veto and step.target_zone in HARD_ZONES:
        errors.append(
            f"{label}: {step.target_zone} is not allowed — fatigue veto "
            "is active, nothing above Z2 this week"
        )
    return errors


def _check_step_hr(step: WorkoutStep, slot: SessionSlot, label: str) -> list[str]:
    # HR bounds (only where the slot has them). Bookend steps may dip
    # below the floor; nothing may exceed the ceiling.
    errors = []
    hr_max, ceiling = step.target_hr_max, slot.hr_bpm_hi
    if hr_max is not None and ceiling is not None and hr_max > ceiling:
        errors.append(
            f"{label}: HR target up to {hr_max} bpm exceeds "
            f"the slot ceiling {ceiling} bpm ({slot.hr_zone_range})"
        )
    hr_min, floor = step.target_hr_min, slot.hr_bpm_lo
    if step.type in _EASY_BOOKENDS or hr_min is None or floor is None:
        return errors
    if hr_min < floor:
        errors.append(
            f"{label}: HR target from {hr_min} bpm is below "
            f"the slot floor {floor} bpm ({slot.hr_zone_range})"
        )
    return errors


def _check_step_pace(step: WorkoutStep, slot: SessionSlot, label: str) -> list[str]:
    # Pace bounds, sec/km: lower = faster. Bookends may run slower than
    # the slow bound; nothing may run faster than the fast bound.
    errors = []
    fastest, fast_bound = step.target_pace_min, slot.pace_lo_sec_per_km
    if fastest is not None and fast_bound is not None and fastest < fast_bound:
        errors.append(
            f"{label}: pace target down to {fastest} s/km is "
            f"faster than the slot allows ({fast_bound} s/km)"
        )
    slowest, slow_bound = step.target_pace_max, slot.pace_hi_sec_per_km
    if step.type in _EASY_BOOKENDS or slowest is None or slow_bound is None:
        return errors
    if slowest > slow_bound:
        errors.append(
            f"{label}: pace target up to {slowest} s/km is "
            f"slower than the slot allows ({slow_bound} s/km)"
        )
    return errors


def _check_steps(
    workout: GeneratedWorkout, slot: SessionSlot | None, constraints: WeekConstraints
) -> list[str]:
    """Per-step checks: durations, enums, HR/pace bounds, fatigue zones."""
    errors = []
    for i, step in enumerate(workout.steps):
        label = f"{workout.date} '{workout.name}' step {i + 1} ({step.type!r})"
        errors.extend(_check_step_schema(step, label, constraints))
        if slot is None:
            continue
        errors.extend(_check_step_hr(step, slot, label))
        errors.extend(_check_step_pace(step, slot, label))
    return errors


def _workouts_by_date(week: GeneratedWeek) -> dict[date, list[GeneratedWorkout]]:
    by_date: dict[date, list[GeneratedWorkout]] = {}
    for workout in week.workouts:
        by_date.setdefault(workout.date, []).append(workout)
    return by_date


def _check_slot_coverage(
    week: GeneratedWeek,
    constraints: WeekConstraints,
    by_date: dict[date, list[GeneratedWorkout]],
) -> list[str]:
    """One workout per slot date, none elsewhere, all within the week."""
    errors = []
    slot_dates = {s.date for s in constraints.sessions}
    week_end = constraints.week_start + timedelta(days=6)
    for workout in week.workouts:
        if not (constraints.week_start <= workout.date <= week_end):
            errors.append(
                f"{workout.date} '{workout.name}': outside the week "
                f"{constraints.week_start} – {week_end}"
            )
        elif workout.date not in slot_dates:
            errors.append(
                f"{workout.date} '{workout.name}': no session slot on this day "
                "(not an allowed training day)"
            )
    for slot in constraints.sessions:
        found = by_date.get(slot.date, [])
        if not found:
            errors.append(f"{slot.date}: missing workout for the {slot.type} slot")
        elif len(found) > 1:
            errors.append(f"{slot.date}: {len(found)} workouts for one slot")
    return errors


def _check_workout_distance(
    workout: GeneratedWorkout, slot: SessionSlot, distance: float
) -> list[str]:
    lo = slot.distance_km_lo * (1 - DISTANCE_TOLERANCE)
    hi = slot.distance_km_hi * (1 + DISTANCE_TOLERANCE)
    if lo <= distance <= hi:
        return []
    return [
        f"{workout.date} '{workout.name}': ~{distance:.1f} km is outside "
        f"the {slot.type} slot range {slot.distance_km_lo}-"
        f"{slot.distance_km_hi} km"
    ]


def _check_week_totals(
    constraints: WeekConstraints, total_km: float, quality_km: float
) -> list[str]:
    """Intensity budget (80/20) and total volume against the slot upper bounds."""
    errors = []
    if quality_km > constraints.intensity_budget_km + SUM_TOLERANCE_KM:
        errors.append(
            f"Quality sessions total ~{quality_km:.1f} km, over the intensity "
            f"budget of {constraints.intensity_budget_km} km (80/20 rule)"
        )
    volume_hi = sum(s.distance_km_hi for s in constraints.sessions)
    if total_km > volume_hi + SUM_TOLERANCE_KM:
        errors.append(
            f"Total volume ~{total_km:.1f} km exceeds the weekly target upper "
            f"bound of {volume_hi:.1f} km"
        )
    return errors


def _check_distances(
    week: GeneratedWeek, constraints: WeekConstraints, slots: dict[date, SessionSlot]
) -> list[str]:
    """Distances: per-workout, intensity budget, total volume."""
    errors: list[str] = []
    total_km = quality_km = 0.0
    for workout in week.workouts:
        slot = slots.get(workout.date)
        distance = _workout_distance_km(workout, slot) if slot is not None else None
        if slot is None or distance is None:
            continue  # no slot, or no pace info anywhere — distance checks skipped
        total_km += distance
        errors.extend(_check_workout_distance(workout, slot, distance))
        if slot.type == "quality":
            quality_km += distance
    return errors + _check_week_totals(constraints, total_km, quality_km)


def _check_hard_days(week: GeneratedWeek, slots: dict[date, SessionSlot]) -> list[str]:
    # A day counts as hard when its slot is a quality slot, or the LLM
    # smuggled intensity (Z4+) into an easy slot. Z3 tops out long/aerobic
    # slots by design, so Z3 alone does not make a day hard.
    hard_dates = set()
    for workout in week.workouts:
        slot_opt = slots.get(workout.date)
        smuggled = any(s.target_zone in ("Z4", "Z5") for s in workout.steps)
        if (slot_opt and slot_opt.type == "quality") or smuggled:
            hard_dates.add(workout.date)
    if len(hard_dates) <= 2:
        return []
    return [
        f"{len(hard_dates)} hard days — max 2 per week "
        f"({', '.join(str(d) for d in sorted(hard_dates))})"
    ]


def _check_injury_adjacency(
    workout_dates: list[date], constraints: WeekConstraints
) -> list[str]:
    if not constraints.injury_flags:
        return []
    days_sorted = sorted(workout_dates)
    return [
        f"Back-to-back runs {a} and {b} with injury flag "
        f"'{constraints.injury_flags[0]}' — consecutive run days "
        "are not allowed"
        for a, b in zip(days_sorted, days_sorted[1:])
        if (b - a).days == 1
    ]


def validate_week(week: GeneratedWeek, constraints: WeekConstraints) -> list[str]:
    """All guardrail errors for `week`; empty list = valid.

    Example:
        >>> validate_week(fallback_week(constraints), constraints)
        []
    """
    slots = {s.date: s for s in constraints.sessions}
    by_date = _workouts_by_date(week)
    errors = _check_slot_coverage(week, constraints, by_date)
    errors += _check_distances(week, constraints, slots)
    for workout in week.workouts:
        errors.extend(_check_steps(workout, slots.get(workout.date), constraints))
    # Hard-day guardrails mirror the constraint engine's rules.
    errors += _check_hard_days(week, slots)
    errors += _check_injury_adjacency(list(by_date), constraints)
    return errors
