"""Workout library business logic: CRUD, duplication and Garmin push.

Every lookup is scoped to the requesting user; another user's workout is
indistinguishable from a missing one (404).
"""

import logging
from datetime import date

from fastapi import HTTPException, status
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..garmin.client import GarminClient
from ..garmin.push import _require_login
from ..models import User
from .estimates import estimated_distance_m, estimated_duration_sec, executed_step_count
from .garmin_mapper import library_workout_to_garmin_json
from .models import LibraryWorkout, LibraryWorkoutPush, utc_now
from .schemas import (
    BuilderStep,
    LibraryWorkoutInput,
    LibraryWorkoutOut,
    LibraryWorkoutPushOut,
    LibraryWorkoutSummaryOut,
    RepeatBlock,
    WorkoutItem,
)

logger = logging.getLogger(__name__)
_ITEMS_ADAPTER: TypeAdapter[list[BuilderStep | RepeatBlock]] = TypeAdapter(
    list[WorkoutItem]
)
COPY_SUFFIX = " (copy)"
NAME_MAX_LENGTH = 100


def stored_items(row: LibraryWorkout) -> list[BuilderStep | RepeatBlock]:
    """Parse a row's JSON ``steps`` back into builder models.

    Example:
        >>> stored_items(row)[0].kind
        'step'
    """
    return _ITEMS_ADAPTER.validate_python(row.steps)


def to_push_out(push: LibraryWorkoutPush) -> LibraryWorkoutPushOut:
    """API view of one push record.

    Example:
        >>> to_push_out(push).date.isoformat()
        '2026-10-21'
    """
    return LibraryWorkoutPushOut(
        date=push.date,
        garmin_workout_id=push.garmin_workout_id,
        pushed_at=push.pushed_at,
    )


def to_workout_out(row: LibraryWorkout) -> LibraryWorkoutOut:
    """Full API view of a workout, pushes newest first.

    Example:
        >>> to_workout_out(row).estimated_duration_sec
        1800
    """
    items = stored_items(row)
    pushes = sorted(row.pushes, key=lambda p: (p.pushed_at, p.id), reverse=True)
    return LibraryWorkoutOut(
        id=row.id,
        name=row.name,
        description=row.description,
        steps=items,
        estimated_duration_sec=estimated_duration_sec(items),
        estimated_distance_m=estimated_distance_m(items),
        created_at=row.created_at,
        updated_at=row.updated_at,
        pushes=[to_push_out(p) for p in pushes],
    )


def to_summary_out(row: LibraryWorkout) -> LibraryWorkoutSummaryOut:
    """List-view summary of a workout with expanded step count.

    Example:
        >>> to_summary_out(row).step_count
        10
    """
    items = stored_items(row)
    return LibraryWorkoutSummaryOut(
        id=row.id,
        name=row.name,
        description=row.description,
        step_count=executed_step_count(items),
        estimated_duration_sec=estimated_duration_sec(items),
        estimated_distance_m=estimated_distance_m(items),
        updated_at=row.updated_at,
    )


def list_workouts(db: Session, user: User) -> list[LibraryWorkout]:
    """The user's workouts, most recently updated first.

    Example:
        >>> [w.name for w in list_workouts(db, user)]
        ['Tempo', 'Long run']
    """
    query = (
        select(LibraryWorkout)
        .where(LibraryWorkout.user_id == user.id)
        .order_by(LibraryWorkout.updated_at.desc(), LibraryWorkout.id.desc())
    )
    return list(db.scalars(query))


def get_owned_workout(db: Session, user: User, workout_id: int) -> LibraryWorkout:
    """Fetch one of the user's workouts or raise 404.

    Example:
        >>> get_owned_workout(db, user, 3).id
        3
    """
    row = db.get(LibraryWorkout, workout_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Library workout id={workout_id} not found; expected an id from GET /api/workouts",
        )
    return row


def create_workout(
    db: Session, user: User, payload: LibraryWorkoutInput
) -> LibraryWorkout:
    """Persist a new workout for ``user``.

    Example:
        >>> create_workout(db, user, payload).name
        'Tempo'
    """
    row = LibraryWorkout(user_id=user.id, steps=[])
    _apply_input(row, payload)
    db.add(row)
    db.commit()
    return row


def _apply_input(row: LibraryWorkout, payload: LibraryWorkoutInput) -> None:
    """Copy validated input onto a row (steps stored as JSON-ready dicts)."""
    row.name = payload.name
    row.description = payload.description
    row.steps = [item.model_dump(mode="json") for item in payload.steps]


def update_workout(
    db: Session, row: LibraryWorkout, payload: LibraryWorkoutInput
) -> LibraryWorkout:
    """Replace a workout's name, description and steps.

    Example:
        >>> update_workout(db, row, payload).updated_at > row.created_at
        True
    """
    _apply_input(row, payload)
    row.updated_at = utc_now()
    db.commit()
    return row


def delete_workout(db: Session, row: LibraryWorkout) -> None:
    """Delete a workout and its push history.

    Example:
        >>> delete_workout(db, row)
    """
    db.delete(row)
    db.commit()


def copy_name(name: str) -> str:
    """Name for a duplicate, trimmed so it stays within the 100-char limit.

    Example:
        >>> copy_name("Tempo")
        'Tempo (copy)'
    """
    return name[: NAME_MAX_LENGTH - len(COPY_SUFFIX)] + COPY_SUFFIX


def duplicate_workout(db: Session, user: User, row: LibraryWorkout) -> LibraryWorkout:
    """Create a copy of ``row`` named "<name> (copy)" without push history.

    Example:
        >>> duplicate_workout(db, user, row).name
        'Tempo (copy)'
    """
    copy = LibraryWorkout(
        user_id=user.id,
        name=copy_name(row.name),
        description=row.description,
        steps=list(row.steps),
    )
    db.add(copy)
    db.commit()
    return copy


def _log_push_failure(row: LibraryWorkout, target_date: date, exc: Exception) -> None:
    """Structured warning for a failed library push (no credentials logged)."""
    logger.warning(
        "Garmin library push failed for workout %s on %s: %s",
        row.id,
        target_date.isoformat(),
        exc,
        extra={
            "dataset": "library_push",
            "library_workout_id": row.id,
            "date": target_date.isoformat(),
            "error": repr(exc),
        },
    )


def _upload(row: LibraryWorkout, target_date: date, client: GarminClient) -> str:
    """Upload + schedule on Garmin; any client error becomes a 502."""
    payload = LibraryWorkoutInput(
        name=row.name, description=row.description, steps=stored_items(row)
    )
    try:
        return client.schedule_workout(
            library_workout_to_garmin_json(payload), target_date
        )
    except Exception as exc:  # noqa: BLE001 — surface any Garmin failure as 502
        _log_push_failure(row, target_date, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Garmin upload failed: {exc}"
        ) from exc


def push_workout(
    db: Session, row: LibraryWorkout, target_date: date, client: GarminClient
) -> LibraryWorkoutPush:
    """Schedule ``row`` on ``target_date`` in Garmin and record the push.

    Raises 401 (login/MFA required) like the week push, or 502 on upload
    failure. Pushing twice to the same date creates two calendar entries.

    Example:
        >>> push_workout(db, row, date(2026, 10, 21), client).garmin_workout_id
        '123456789'
    """
    _require_login(client)
    garmin_id = _upload(row, target_date, client)
    push = LibraryWorkoutPush(
        library_workout_id=row.id, date=target_date, garmin_workout_id=garmin_id
    )
    row.pushes.append(push)
    db.commit()
    return push
