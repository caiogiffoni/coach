from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..coaching.zones import compute_zones
from ..db import get_db
from ..models import User
from .models import Profile
from .seed import has_imported_data, seed_profile_from_data

router = APIRouter(prefix="/api/profile", tags=["profile"])

GoalMode = Literal["race", "health"]
RaceDistance = Literal["5K", "10K", "HM", "MARATHON"]
Weekday = Annotated[int, Field(ge=0, le=6)]  # 0=Mon..6=Sun


class ProfileUpdate(BaseModel):
    """Partial update: only provided fields are applied (None clears a field)."""

    max_hr: int | None = None
    resting_hr: int | None = None
    threshold_pace_sec_per_km: int | None = None
    threshold_hr: int | None = None
    recent_race_distance_km: float | None = None
    recent_race_time_sec: int | None = None
    current_weekly_volume_km: float | None = None
    injury_history: list[str] | None = None
    goal_mode: GoalMode | None = None
    goal_race_distance: RaceDistance | None = None
    goal_race_date: date | None = None
    preferred_days: list[Weekday] | None = None


class ProfileResponse(BaseModel):
    max_hr: int | None
    resting_hr: int | None
    threshold_pace_sec_per_km: int | None
    threshold_hr: int | None
    recent_race_distance_km: float | None
    recent_race_time_sec: int | None
    current_weekly_volume_km: float | None
    injury_history: list[str]
    goal_mode: str
    goal_race_distance: str | None
    goal_race_date: date | None
    preferred_days: list[int]
    seeded_at: datetime | None


class HrZoneResponse(BaseModel):
    zone: str
    min_bpm: int
    max_bpm: int


class PaceZoneResponse(BaseModel):
    name: str
    min_sec_per_km: int
    max_sec_per_km: int


class ZonesResponse(BaseModel):
    hr_zones: list[HrZoneResponse] | None
    hr_source: str | None  # "lthr" | "karvonen"
    pace_zones: list[PaceZoneResponse] | None
    threshold_pace_sec_per_km: int | None
    threshold_pace_source: str | None  # "profile" | "race_estimate"
    weekly_ceiling_km: float | None
    intensity_budget_km: float | None


def _get_profile(user: User, db: Session) -> Profile | None:
    return db.scalar(select(Profile).where(Profile.user_id == user.id))


@router.get("", response_model=ProfileResponse)
def get_profile(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Profile:
    profile = _get_profile(user, db)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return profile


@router.put("", response_model=ProfileResponse)
def upsert_profile(
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Profile:
    profile = _get_profile(user, db)
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    if profile.goal_mode == "race" and not (
        profile.goal_race_distance and profile.goal_race_date
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "goal_mode='race' requires goal_race_distance and goal_race_date",
        )

    db.commit()
    db.refresh(profile)
    return profile


@router.post("/seed", response_model=ProfileResponse)
def seed_profile(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Profile:
    if not has_imported_data(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "No imported data to seed from")
    return seed_profile_from_data(user.id, db)


@router.get("/zones", response_model=ZonesResponse)
def get_zones(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    profile = _get_profile(user, db)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return compute_zones(profile)
