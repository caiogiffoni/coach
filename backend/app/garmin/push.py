"""Idempotent Garmin push for approved week plans (PLAN.md step 7).

A push uploads every workout in an approved week to Garmin Connect, replacing
only workouts the app created previously (tracked by ``GarminWorkoutMapping``).
If a day already has a workout on Garmin that the app did not create, that day
is skipped with a warning.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..coaching.plan_models import WeekPlan, Workout
from ..models import User
from .client import GarminClient
from .mapper import workout_to_garmin_json
from .models import GarminWorkoutMapping

logger = logging.getLogger(__name__)


@dataclass
class PushReport:
    """Result of pushing one week's workouts to Garmin Connect."""

    pushed_dates: list[str] = field(default_factory=list)
    skipped_dates: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return {
            "pushed_dates": self.pushed_dates,
            "skipped_dates": self.skipped_dates,
            "errors": self.errors,
        }


def _require_login(client: GarminClient) -> None:
    """Ensure the client is authenticated; raise HTTP 401 otherwise."""
    result = client.login()
    if result.needs_mfa:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"MFA required: {result.message}",
        )
    if not result.success:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Garmin login failed: {result.message}",
        )


def _load_approved_plan(db: Session, user: User, week_start: date) -> WeekPlan:
    """Return the user's plan for ``week_start``; 404 if missing, 409 if unapproved."""
    plan = db.scalar(
        select(WeekPlan).where(
            WeekPlan.user_id == user.id, WeekPlan.week_start == week_start
        )
    )
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No plan for this week")
    if plan.status != "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Week {week_start} must be approved before pushing (status={plan.status})",
        )
    return plan


def _week_mapping_ids(db: Session, plan_id: int) -> set[str]:
    """All Garmin workout IDs the app created for this week (collision check)."""
    return {
        str(m.garmin_workout_id)
        for m in db.scalars(
            select(GarminWorkoutMapping).where(
                GarminWorkoutMapping.week_plan_id == plan_id
            )
        )
    }


@dataclass
class _PushContext:
    """Per-week state shared by every workout push in ``push_week``."""

    plan_id: int
    db: Session
    client: GarminClient
    week_mapping_ids: set[str]  # app-created Garmin IDs (collision check)
    report: PushReport


def push_week(
    week_start: date,
    user: User,
    db: Session,
    client: GarminClient,
) -> PushReport:
    """Push the approved week starting on ``week_start`` for ``user``.

    Raises ``HTTPException(409)`` if the week is not approved, or
    ``HTTPException(401)`` if the Garmin client cannot log in.

    Example:
        ``push_week(date(2026, 5, 11), user, db, client).pushed_dates``
    """
    plan = _load_approved_plan(db, user, week_start)
    _require_login(client)

    ctx = _PushContext(
        plan.id, db, client, _week_mapping_ids(db, plan.id), PushReport()
    )
    for workout in sorted(plan.workouts, key=lambda w: w.date):
        _push_workout_best_effort(workout, ctx)

    plan.status = "pushed"
    db.commit()

    return ctx.report


def _log_push_failure(
    dataset: str, workout: Workout, exc: Exception, **fields: object
) -> None:
    """Structured warning for a per-day push failure (no credentials logged)."""
    logger.warning(
        "Garmin %s failed for %s: %s",
        dataset,
        workout.date.isoformat(),
        exc,
        extra={
            "dataset": dataset,
            "date": workout.date.isoformat(),
            "error": repr(exc),
            **fields,
        },
    )


def _push_workout_best_effort(workout: Workout, ctx: _PushContext) -> None:
    """Push one workout; record (and log) failures so remaining days still push."""
    try:
        _push_workout(workout, ctx)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — keep pushing remaining days
        _log_push_failure("push_workout", workout, exc, week_plan_id=ctx.plan_id)
        ctx.report.errors.append(f"{workout.date.isoformat()}: {exc}")


def _delete_previous_upload(workout: Workout, ctx: _PushContext) -> None:
    """Delete any previous app-created workout for this (week, date)."""
    existing = ctx.db.scalar(
        select(GarminWorkoutMapping).where(
            GarminWorkoutMapping.week_plan_id == ctx.plan_id,
            GarminWorkoutMapping.date == workout.date,
        )
    )
    if existing is None:
        return
    old_id = existing.garmin_workout_id
    try:
        ctx.client.delete_workout(old_id)
    except Exception as exc:  # noqa: BLE001 — stale upload; still replace mapping
        _log_push_failure("delete_workout", workout, exc, garmin_workout_id=old_id)
        ctx.report.errors.append(f"Could not delete previous workout {old_id}: {exc}")
    ctx.db.delete(existing)
    ctx.week_mapping_ids.discard(str(old_id))
    ctx.db.flush()


def _foreign_collision_reason(workout: Workout, ctx: _PushContext) -> str | None:
    """Skip reason when the date has workouts we did not create, else None."""
    scheduled = ctx.client.get_workouts_for_date(workout.date)
    collisions = [
        s for s in scheduled if str(s["workoutId"]) not in ctx.week_mapping_ids
    ]
    if not collisions:
        return None
    names = ", ".join(c.get("name", "Unknown") for c in collisions)
    return f"{workout.date.strftime('%A')} already has {names} — not ours, leaving it alone"


def _push_workout(workout: Workout, ctx: _PushContext) -> None:
    """Push a single workout, idempotently replacing a previous app upload."""
    # 1. Delete any previous app-created workout for this (week, date).
    _delete_previous_upload(workout, ctx)

    # 2. Collision check: are there workouts on this date we did not create?
    reason = _foreign_collision_reason(workout, ctx)
    if reason is not None:
        ctx.report.skipped_dates.append(
            {"date": workout.date.isoformat(), "reason": reason}
        )
        return

    # 3. Upload and schedule.
    garmin_json = workout_to_garmin_json(workout)
    garmin_id = ctx.client.schedule_workout(garmin_json, workout.date)
    ctx.db.add(
        GarminWorkoutMapping(
            week_plan_id=ctx.plan_id, date=workout.date, garmin_workout_id=garmin_id
        )
    )
    workout.status = "pushed"
    ctx.db.flush()

    ctx.week_mapping_ids.add(garmin_id)
    ctx.report.pushed_dates.append(workout.date.isoformat())
