"""
Week-plan storage service: generate / regenerate a stored WeekPlan.

Moved out of router.py so the router stays a thin HTTP layer. Errors are
raised as WeekPlanError subclasses; the router maps them to HTTP statuses.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..llm.client import LLMClient
from ..profile.models import Profile
from .constraints import SessionSlot, WeekConstraints
from .generator import generate_day, generate_week
from .plan_models import WeekPlan, Workout
from .validator import GeneratedWeek, GeneratedWorkout, WorkoutStep


class WeekPlanError(Exception):
    """Base class for week-plan request errors (mapped to HTTP by the router)."""


class WeekPlanMissingError(WeekPlanError):
    """Per-day regeneration requested before the week was generated."""


class SessionSlotMissingError(WeekPlanError):
    """Per-day regeneration requested for a day with no session slot."""


class WeekPlanLockedError(WeekPlanError):
    """Whole-week regeneration requested for a non-draft week."""


def get_user_week_plan(db: Session, user_id: int, week_start: date) -> WeekPlan | None:
    """The user's stored plan for the week starting ``week_start``, if any.

    Example:
        >>> get_user_week_plan(db, user.id, date(2026, 6, 1)) is None
        True
    """
    return db.scalar(
        select(WeekPlan).where(
            WeekPlan.user_id == user_id, WeekPlan.week_start == week_start
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


def _replace_workouts(
    plan: WeekPlan, week: GeneratedWeek, constraints: WeekConstraints
) -> None:
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


def _slot_on(constraints: WeekConstraints, day_date: date) -> SessionSlot:
    slot = next((s for s in constraints.sessions if s.date == day_date), None)
    if slot is None:
        raise SessionSlotMissingError(f"No session slot on {day_date} for this week")
    return slot


def regenerate_plan_day(
    db: Session,
    plan: WeekPlan | None,
    constraints: WeekConstraints,
    profile: Profile,
    day_date: date,
    notes: str | None,
    llm: LLMClient | None,
) -> WeekPlan:
    """Regenerate just ``day_date`` within the existing draft and commit.

    ``notes`` of None keeps the plan's stored notes.

    Example:
        >>> plan = regenerate_plan_day(db, plan, c, profile, date(2026, 6, 3), None, None)
    """
    if plan is None:
        raise WeekPlanMissingError("No plan for this week — generate the week first")
    slot = _slot_on(constraints, day_date)
    notes = notes if notes is not None else plan.notes
    result = generate_day(slot, constraints, profile, notes, llm, _to_generated(plan))
    _replace_workouts(plan, result.week, constraints)
    plan.notes = notes
    plan.validation_errors = result.errors
    db.commit()
    db.refresh(plan)
    return plan


def regenerate_plan_week(
    db: Session,
    user_id: int,
    plan: WeekPlan | None,
    constraints: WeekConstraints,
    profile: Profile,
    notes: str | None,
    llm: LLMClient | None,
) -> WeekPlan:
    """Generate the whole week, replacing an existing draft in one transaction.

    Example:
        >>> plan = regenerate_plan_week(db, user.id, None, c, profile, None, None)
        >>> plan.status
        'draft'
    """
    if plan is not None and plan.status != "draft":
        raise WeekPlanLockedError(
            f"Week {constraints.week_start} is already {plan.status}"
        )
    result = generate_week(constraints, profile, notes, llm)
    if plan is not None:
        db.delete(plan)  # children cascade; replaced in the same transaction
        db.flush()
    plan = WeekPlan(
        user_id=user_id,
        week_start=constraints.week_start,
        goal_mode=constraints.goal_mode,
        notes=notes or "",
        source=result.source,
        validation_errors=result.errors,
    )
    db.add(plan)
    _replace_workouts(plan, result.week, constraints)
    db.commit()
    db.refresh(plan)
    return plan
