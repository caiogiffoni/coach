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


def _workout_distance_km(
    workout: GeneratedWorkout, slot: SessionSlot
) -> float | None:
    parts = [_step_distance_km(s, slot) for s in workout.steps]
    known = [p for p in parts if p is not None]
    return sum(known) if known else None


def _check_steps(
    workout: GeneratedWorkout, slot: SessionSlot | None, constraints: WeekConstraints
) -> list[str]:
    """Per-step checks: durations, enums, HR/pace bounds, fatigue zones."""
    errors = []
    for i, step in enumerate(workout.steps):
        label = f"{workout.date} '{workout.name}' step {i + 1} ({step.type!r})"
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
        if slot is None:
            continue
        # HR bounds (only where the slot has them). Bookend steps may dip
        # below the floor; nothing may exceed the ceiling.
        if step.target_hr_max is not None and slot.hr_bpm_hi is not None:
            if step.target_hr_max > slot.hr_bpm_hi:
                errors.append(
                    f"{label}: HR target up to {step.target_hr_max} bpm exceeds "
                    f"the slot ceiling {slot.hr_bpm_hi} bpm ({slot.hr_zone_range})"
                )
        if (
            step.type not in _EASY_BOOKENDS
            and step.target_hr_min is not None
            and slot.hr_bpm_lo is not None
            and step.target_hr_min < slot.hr_bpm_lo
        ):
            errors.append(
                f"{label}: HR target from {step.target_hr_min} bpm is below "
                f"the slot floor {slot.hr_bpm_lo} bpm ({slot.hr_zone_range})"
            )
        # Pace bounds, sec/km: lower = faster. Bookends may run slower than
        # the slow bound; nothing may run faster than the fast bound.
        if step.target_pace_min is not None and slot.pace_lo_sec_per_km is not None:
            if step.target_pace_min < slot.pace_lo_sec_per_km:
                errors.append(
                    f"{label}: pace target down to {step.target_pace_min} s/km is "
                    f"faster than the slot allows ({slot.pace_lo_sec_per_km} s/km)"
                )
        if (
            step.type not in _EASY_BOOKENDS
            and step.target_pace_max is not None
            and slot.pace_hi_sec_per_km is not None
            and step.target_pace_max > slot.pace_hi_sec_per_km
        ):
            errors.append(
                f"{label}: pace target up to {step.target_pace_max} s/km is "
                f"slower than the slot allows ({slot.pace_hi_sec_per_km} s/km)"
            )
    return errors


def validate_week(week: GeneratedWeek, constraints: WeekConstraints) -> list[str]:
    """All guardrail errors for `week`; empty list = valid."""
    errors: list[str] = []
    slots = {s.date: s for s in constraints.sessions}
    week_end = constraints.week_start + timedelta(days=6)

    # --- one workout per slot date, none elsewhere, all within the week ---
    by_date: dict[date, list[GeneratedWorkout]] = {}
    for workout in week.workouts:
        by_date.setdefault(workout.date, []).append(workout)
        if not (constraints.week_start <= workout.date <= week_end):
            errors.append(
                f"{workout.date} '{workout.name}': outside the week "
                f"{constraints.week_start} – {week_end}"
            )
        elif workout.date not in slots:
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

    # --- distances: per-workout, intensity budget, total volume ---
    total_km = quality_km = 0.0
    for workout in week.workouts:
        slot = slots.get(workout.date)
        if slot is None:
            continue
        distance = _workout_distance_km(workout, slot)
        if distance is None:
            continue  # no pace info anywhere — distance checks skipped
        total_km += distance
        lo = slot.distance_km_lo * (1 - DISTANCE_TOLERANCE)
        hi = slot.distance_km_hi * (1 + DISTANCE_TOLERANCE)
        if not (lo <= distance <= hi):
            errors.append(
                f"{workout.date} '{workout.name}': ~{distance:.1f} km is outside "
                f"the {slot.type} slot range {slot.distance_km_lo}-"
                f"{slot.distance_km_hi} km"
            )
        if slot.type == "quality":
            quality_km += distance
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

    # --- per-step checks ---
    for workout in week.workouts:
        errors.extend(_check_steps(workout, slots.get(workout.date), constraints))

    # --- hard-day guardrails (mirror of the constraint engine's rules) ---
    # A day counts as hard when its slot is a quality slot, or the LLM
    # smuggled intensity (Z4+) into an easy slot. Z3 tops out long/aerobic
    # slots by design, so Z3 alone does not make a day hard.
    hard_dates = set()
    for workout in week.workouts:
        slot = slots.get(workout.date)
        smuggled = any(s.target_zone in ("Z4", "Z5") for s in workout.steps)
        if (slot and slot.type == "quality") or smuggled:
            hard_dates.add(workout.date)
    if len(hard_dates) > 2:
        errors.append(
            f"{len(hard_dates)} hard days — max 2 per week "
            f"({', '.join(str(d) for d in sorted(hard_dates))})"
        )

    if constraints.injury_flags:
        days_sorted = sorted(by_date)
        for a, b in zip(days_sorted, days_sorted[1:]):
            if (b - a).days == 1:
                errors.append(
                    f"Back-to-back runs {a} and {b} with injury flag "
                    f"'{constraints.injury_flags[0]}' — consecutive run days "
                    "are not allowed"
                )

    return errors
