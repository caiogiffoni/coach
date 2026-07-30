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
from .generator import generate_day, generate_week
from .guard import DayGuardResult, check_day_guard
from .plan_models import WeekPlan, Workout
from .validator import GeneratedWeek, GeneratedWorkout, WorkoutStep

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


def _get_plan(db: Session, user: User, week_start: date) -> WeekPlan | None:
    return db.scalar(
        select(WeekPlan).where(
            WeekPlan.user_id == user.id, WeekPlan.week_start == week_start
        )
    )


def _to_generated(plan: WeekPlan) -> GeneratedWeek:
    """Stored rows → the validator's week model (for re-validation)."""
    return GeneratedWeek(
        workouts=[
            GeneratedWorkout(
                name=w.name,
                date=w.date,
                sport=w.sport,
                duration_min=w.duration_min,
                description=w.description,
                steps=[WorkoutStep.model_validate(s) for s in w.steps],
            )
            for w in plan.workouts
        ]
    )


def _replace_workouts(plan: WeekPlan, week: GeneratedWeek, constraints: WeekConstraints):
    """Swap the plan's Workout rows for `week`'s (same session/transaction)."""
    slots = {s.date: s for s in constraints.sessions}
    plan.workouts.clear()
    plan.workouts.extend(
        Workout(
            date=w.date,
            name=w.name,
            sport=w.sport,
            duration_min=w.duration_min,
            description=w.description,
            steps=[s.model_dump(mode="json") for s in w.steps],
            slot_type=slots[w.date].type,
        )
        for w in week.workouts
    )


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
    plan = _get_plan(db, user, constraints.week_start)

    if body.day_date is not None:
        if plan is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No plan for this week — generate the week first",
            )
        slot = next(
            (s for s in constraints.sessions if s.date == body.day_date), None
        )
        if slot is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No session slot on {body.day_date} for this week",
            )
        notes = body.notes if body.notes is not None else plan.notes
        result = generate_day(slot, constraints, profile, notes, llm, _to_generated(plan))
        _replace_workouts(plan, result.week, constraints)
        plan.notes = notes
        plan.validation_errors = result.errors
        db.commit()
        db.refresh(plan)
        return plan

    if plan is not None and plan.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Week {constraints.week_start} is already {plan.status}",
        )
    result = generate_week(constraints, profile, body.notes, llm)
    if plan is not None:
        db.delete(plan)  # children cascade; replaced in the same transaction
        db.flush()
    plan = WeekPlan(
        user_id=user.id,
        week_start=constraints.week_start,
        goal_mode=constraints.goal_mode,
        notes=body.notes or "",
        source=result.source,
        validation_errors=result.errors,
    )
    db.add(plan)
    _replace_workouts(plan, result.week, constraints)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/weeks/{week_start}", response_model=WeekPlanResponse)
def get_week_plan(
    week_start: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WeekPlan:
    plan = _get_plan(db, user, week_start)
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
    plan = _get_plan(db, user, week_start)
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
