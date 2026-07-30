"""Idempotent Garmin push for approved week plans (PLAN.md step 7).

A push uploads every workout in an approved week to Garmin Connect, replacing
only workouts the app created previously (tracked by ``GarminWorkoutMapping``).
If a day already has a workout on Garmin that the app did not create, that day
is skipped with a warning.
"""

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


def push_week(
    week_start: date,
    user: User,
    db: Session,
    client: GarminClient,
) -> PushReport:
    """Push the approved week starting on ``week_start`` for ``user``.

    Raises ``HTTPException(409)`` if the week is not approved, or
    ``HTTPException(401)`` if the Garmin client cannot log in.
    """
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

    _require_login(client)

    report = PushReport()

    # All mapping IDs for this week, used for collision detection.
    week_mapping_ids = {
        str(m.garmin_workout_id)
        for m in db.scalars(
            select(GarminWorkoutMapping).where(
                GarminWorkoutMapping.week_plan_id == plan.id
            )
        )
    }

    workouts = sorted(plan.workouts, key=lambda w: w.date)

    for workout in workouts:
        try:
            _push_workout(
                workout=workout,
                plan_id=plan.id,
                db=db,
                client=client,
                week_mapping_ids=week_mapping_ids,
                report=report,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — keep pushing remaining days
            report.errors.append(f"{workout.date.isoformat()}: {exc}")

    plan.status = "pushed"
    db.commit()

    return report


def _push_workout(
    workout: Workout,
    plan_id: int,
    db: Session,
    client: GarminClient,
    week_mapping_ids: set[str],
    report: PushReport,
) -> None:
    """Push a single workout, idempotently replacing a previous app upload."""
    # 1. Delete any previous app-created workout for this (week, date).
    existing = db.scalar(
        select(GarminWorkoutMapping).where(
            GarminWorkoutMapping.week_plan_id == plan_id,
            GarminWorkoutMapping.date == workout.date,
        )
    )
    if existing is not None:
        try:
            client.delete_workout(existing.garmin_workout_id)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(
                f"Could not delete previous workout {existing.garmin_workout_id}: {exc}"
            )
        db.delete(existing)
        week_mapping_ids.discard(str(existing.garmin_workout_id))
        db.flush()

    # 2. Collision check: are there workouts on this date we did not create?
    scheduled = client.get_workouts_for_date(workout.date)
    collisions = [s for s in scheduled if str(s["workoutId"]) not in week_mapping_ids]
    if collisions:
        names = ", ".join(c.get("name", "Unknown") for c in collisions)
        report.skipped_dates.append(
            {
                "date": workout.date.isoformat(),
                "reason": f"{workout.date.strftime('%A')} already has {names} — not ours, leaving it alone",
            }
        )
        return

    # 3. Upload and schedule.
    garmin_json = workout_to_garmin_json(workout)
    garmin_id = client.schedule_workout(garmin_json, workout.date)

    mapping = GarminWorkoutMapping(
        week_plan_id=plan_id,
        date=workout.date,
        garmin_workout_id=garmin_id,
    )
    db.add(mapping)
    workout.status = "pushed"
    db.flush()

    week_mapping_ids.add(garmin_id)
    report.pushed_dates.append(workout.date.isoformat())
