"""
Daily guard: compare the stored plan against fresh fatigue data and the
constraints recomputed from the latest synced Garmin data.

If the fresh signals say the athlete is too fatigued for intensity and the
planned workout contains work above Z2, the guard vetoes the day. If the
planned session type no longer matches the slot that the fresh constraints
allocate for that day, the guard recommends a swap.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingestion.api_pull import latest_local_date
from ..profile.models import Profile
from .constraints import TrainingState, WeekConstraints, compute_constraints
from .plan_models import WeekPlan, Workout

# ACWR threshold used as a secondary fatigue signal. Garmin's own status is
# preferred when available.
ACWR_HIGH_THRESHOLD = 1.5


class DayGuardResult(BaseModel):
    date: date
    recommendation: str  # proceed | swap | veto
    reason: str
    current_slot_type: str
    suggested_slot_type: str | None
    data_age_days: int
    fatigue_reasons: list[str]


def _has_intensity_above_z2(workout: Workout) -> bool:
    """Return True if any step targets Z3 or higher."""
    for step in workout.steps:
        zone = step.get("target_zone")
        if isinstance(zone, str) and zone.upper() in ("Z3", "Z4", "Z5"):
            return True
    return False


def _acwr_reason(state: TrainingState) -> str | None:
    """Extra fatigue signal from ACWR when Garmin's status flags a high load."""
    if state.acwr_status and state.acwr_status.upper() in {"HIGH", "VERY_HIGH"}:
        return f"ACWR status {state.acwr_status}"
    if state.acwr is not None and state.acwr > ACWR_HIGH_THRESHOLD:
        return f"ACWR {state.acwr:.2f} above {ACWR_HIGH_THRESHOLD}"
    return None


def _planned_workout(
    db: Session, profile: Profile, week_start: date, day_date: date
) -> Workout:
    """The stored workout for ``day_date``; ValueError when plan/day is missing."""
    plan = db.scalar(
        select(WeekPlan).where(
            WeekPlan.week_start == week_start,
            WeekPlan.user_id == profile.user_id,
        )
    )
    if plan is None:
        raise ValueError(f"No week plan found for {week_start}")
    workout = next((w for w in plan.workouts if w.date == day_date), None)
    if workout is None:
        raise ValueError(f"No workout found for {day_date}")
    return workout


def _fresh_fatigue_reasons(fresh: WeekConstraints) -> list[str]:
    """Reuse the constraint engine's fatigue signals plus ACWR."""
    reasons = list(fresh.fatigue_reasons)
    acwr = _acwr_reason(fresh.state)
    if acwr:
        reasons.append(acwr)
    return reasons


def _recommendation(
    workout: Workout, fatigue_reasons: list[str], suggested_slot_type: str | None
) -> tuple[str, str]:
    """(recommendation, reason): veto beats swap beats proceed."""
    # Veto: fatigue signal present and the workout still contains hard work.
    if fatigue_reasons and _has_intensity_above_z2(workout):
        return "veto", "; ".join(fatigue_reasons)
    # Swap: the planned session type no longer matches the fresh constraints.
    if suggested_slot_type is not None and workout.slot_type != suggested_slot_type:
        return "swap", (
            f"Planned {workout.slot_type} conflicts with fresh "
            f"{suggested_slot_type} slot"
        )
    return "proceed", "Fresh data agrees with the planned session"


def check_day_guard(
    db: Session,
    profile: Profile,
    week_start: date,
    day_date: date,
    days_override: list[int] | None = None,
) -> DayGuardResult:
    """Evaluate the stored workout for ``day_date`` against fresh data.

    Example:
        >>> check_day_guard(db, profile, date(2026, 6, 1), date(2026, 6, 3))
        DayGuardResult(date=..., recommendation='proceed', ...)
    """
    fresh = compute_constraints(db, profile, week_start, days_override)
    workout = _planned_workout(db, profile, week_start, day_date)
    fatigue_reasons = _fresh_fatigue_reasons(fresh)
    # Slot type according to the freshly computed constraints.
    fresh_slot = next((s for s in fresh.sessions if s.date == day_date), None)
    suggested_slot_type = fresh_slot.type if fresh_slot else None
    latest_date = latest_local_date(db) or date.today()
    recommendation, reason = _recommendation(
        workout, fatigue_reasons, suggested_slot_type
    )
    return DayGuardResult(
        date=day_date,
        recommendation=recommendation,
        reason=reason,
        current_slot_type=workout.slot_type,
        suggested_slot_type=suggested_slot_type,
        data_age_days=max(0, (day_date - latest_date).days),
        fatigue_reasons=fatigue_reasons,
    )
