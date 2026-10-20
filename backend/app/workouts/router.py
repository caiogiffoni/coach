"""Workout library endpoints (``/api/workouts``).

Thin HTTP layer; logic lives in ``service.py``. All routes require auth and
only ever touch the current user's workouts.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..db import get_db
from ..garmin.client import GarminClient, garmin_client_or_raise
from ..models import User
from . import service
from .schemas import (
    LibraryWorkoutInput,
    LibraryWorkoutOut,
    LibraryWorkoutPushOut,
    LibraryWorkoutPushRequest,
    LibraryWorkoutSummaryOut,
)

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


@router.get("", response_model=list[LibraryWorkoutSummaryOut])
def list_library_workouts(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[LibraryWorkoutSummaryOut]:
    """List the user's saved workouts, newest ``updated_at`` first."""
    return [service.to_summary_out(r) for r in service.list_workouts(db, user)]


@router.post("", response_model=LibraryWorkoutOut, status_code=status.HTTP_201_CREATED)
def create_library_workout(
    body: LibraryWorkoutInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryWorkoutOut:
    """Save a new workout built in the workout builder."""
    return service.to_workout_out(service.create_workout(db, user, body))


@router.get("/{workout_id}", response_model=LibraryWorkoutOut)
def get_library_workout(
    workout_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryWorkoutOut:
    """Return one saved workout with estimates and push history."""
    return service.to_workout_out(service.get_owned_workout(db, user, workout_id))


@router.put("/{workout_id}", response_model=LibraryWorkoutOut)
def update_library_workout(
    workout_id: int,
    body: LibraryWorkoutInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryWorkoutOut:
    """Replace a saved workout's name, description and steps."""
    row = service.get_owned_workout(db, user, workout_id)
    return service.to_workout_out(service.update_workout(db, row, body))


@router.delete("/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_library_workout(
    workout_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a saved workout (Garmin calendar entries are left untouched)."""
    service.delete_workout(db, service.get_owned_workout(db, user, workout_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workout_id}/duplicate",
    response_model=LibraryWorkoutOut,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_library_workout(
    workout_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryWorkoutOut:
    """Copy a saved workout; the copy's name gets a " (copy)" suffix."""
    row = service.get_owned_workout(db, user, workout_id)
    return service.to_workout_out(service.duplicate_workout(db, user, row))


@router.post("/{workout_id}/push", response_model=LibraryWorkoutPushOut)
def push_library_workout(
    workout_id: int,
    body: LibraryWorkoutPushRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GarminClient = Depends(garmin_client_or_raise),
) -> LibraryWorkoutPushOut:
    """Schedule a saved workout on ``body.date`` in the Garmin calendar."""
    row = service.get_owned_workout(db, user, workout_id)
    return service.to_push_out(service.push_workout(db, row, body.date, client))
