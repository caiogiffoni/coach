from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..db import get_db
from ..llm.client import LLMClient, get_llm_client
from ..models import User
from ..profile.models import Profile
from ..profile.seed import has_imported_data
from .constraints import WeekConstraints, compute_constraints
from .guard import DayGuardResult, check_day_guard
from .plan_models import WeekPlan
from .week_service import (
    SessionSlotMissingError,
    WeekPlanError,
    WeekPlanLockedError,
    WeekPlanMissingError,
    get_user_week_plan,
    regenerate_plan_day,
    regenerate_plan_week,
)

router = APIRouter(prefix="/api/coaching", tags=["coaching"])

Weekday = Annotated[int, Field(ge=0, le=6)]  # 0=Mon..6=Sun


def _parse_days(days: str | None) -> list[int] | None:
    """'1,3,5' → [1, 3, 5] (weekday ints, 0=Mon..6=Sun)."""
    if days is None:
        return None
    parts = days.split(",")
    try:
        parsed = [int(part) for part in parts]
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "days must be comma-separated weekday ints (0=Mon..6=Sun)",
        ) from None
    if not parsed or any(d < 0 or d > 6 for d in parsed):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "days must be comma-separated weekday ints (0=Mon..6=Sun)",
        )
    return sorted(set(parsed))


@router.get("/constraints", response_model=WeekConstraints)
def get_constraints(
    week: date,
    days: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WeekConstraints:
    """
    Hard constraints for the week containing `week` (normalized to Monday).
    `days` optionally overrides the profile's preferred run days.
    """
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    if not has_imported_data(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No imported data to compute constraints from"
        )
    return compute_constraints(db, profile, week, _parse_days(days))


# ---------------------------------------------------------------------------
# Week plans: generate / regenerate / read
# ---------------------------------------------------------------------------


class GenerateWeekRequest(BaseModel):
    week: date  # any date in the target week (normalized to Monday)
    days: list[Weekday] | None = None  # per-week run-day override
    notes: str | None = None  # notes for the coach, injected into the prompt
    day_date: date | None = None  # set → regenerate just this day of the draft


class WorkoutResponse(BaseModel):
    id: int
    date: date
    name: str
    sport: str
    duration_min: float
    description: str
    steps: list[dict]
    slot_type: str
    status: str


class WeekPlanResponse(BaseModel):
    id: int
    week_start: date
    goal_mode: str
    notes: str
    source: str
    status: str
    validation_errors: list[str]
    created_at: datetime
    workouts: list[WorkoutResponse]


class WeekPlanSummary(BaseModel):
    week_start: date
    status: str
    source: str


def _profile_and_data(db: Session, user: User) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    if not has_imported_data(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No imported data to generate a plan from"
        )
    return profile


_PLAN_ERROR_STATUS: dict[type[WeekPlanError], int] = {
    WeekPlanMissingError: status.HTTP_404_NOT_FOUND,
    SessionSlotMissingError: status.HTTP_404_NOT_FOUND,
    WeekPlanLockedError: status.HTTP_409_CONFLICT,
}


@router.post("/weeks/generate", response_model=WeekPlanResponse)
def generate_week_plan(
    body: GenerateWeekRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    llm: LLMClient | None = Depends(get_llm_client),
) -> WeekPlan:
    """
    Generate (or regenerate) the week containing `body.week`. With
    `day_date`, regenerate just that day within the existing draft.
    Regenerating a whole week replaces the existing draft in one transaction.
    """
    profile = _profile_and_data(db, user)
    constraints = compute_constraints(db, profile, body.week, body.days)
    plan = get_user_week_plan(db, user.id, constraints.week_start)
    try:
        if body.day_date is not None:
            return regenerate_plan_day(
                db, plan, constraints, profile, body.day_date, body.notes, llm
            )
        return regenerate_plan_week(
            db, user.id, plan, constraints, profile, body.notes, llm
        )
    except WeekPlanError as exc:
        raise HTTPException(_PLAN_ERROR_STATUS[type(exc)], str(exc)) from None


@router.get("/weeks/{week_start}", response_model=WeekPlanResponse)
def get_week_plan(
    week_start: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WeekPlan:
    plan = get_user_week_plan(db, user.id, week_start)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No plan for this week")
    return plan


@router.post("/weeks/{week_start}/approve", response_model=WeekPlanResponse)
def approve_week_plan(
    week_start: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WeekPlan:
    """Mark a draft week as reviewed → approved (draft→approved only)."""
    plan = get_user_week_plan(db, user.id, week_start)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No plan for this week")
    if plan.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Week {week_start} is already {plan.status}",
        )
    plan.status = "approved"
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/weeks", response_model=list[WeekPlanSummary])
def list_week_plans(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WeekPlan]:
    return list(
        db.scalars(
            select(WeekPlan)
            .where(WeekPlan.user_id == user.id)
            .order_by(WeekPlan.week_start.desc())
        )
    )


# ---------------------------------------------------------------------------
# Daily guard
# ---------------------------------------------------------------------------


@router.get("/guard", response_model=DayGuardResult)
def get_day_guard(
    week_start: date,
    date: date,
    days: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DayGuardResult:
    """Check the stored workout for ``date`` against fresh fatigue data."""
    profile = _profile_and_data(db, user)
    try:
        return check_day_guard(db, profile, week_start, date, _parse_days(days))
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
