"""Week-plan storage service tests (app/coaching/week_service.py)."""

from datetime import date, datetime, timedelta

import pytest
from conftest import make_session

from app.coaching.constraints import compute_constraints
from app.coaching.week_service import (
    SessionSlotMissingError,
    WeekPlanLockedError,
    WeekPlanMissingError,
    get_user_week_plan,
    regenerate_plan_day,
    regenerate_plan_week,
)
from app.ingestion.models import Activity
from app.models import User
from app.profile.models import Profile

MONDAY = date(2026, 6, 1)


class RejectingLLM:
    """Fake LLM that always answers garbage, forcing the fallback path."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system: str, user: str) -> str:
        self.calls += 1
        return "not json"


@pytest.fixture()
def seeded():
    db = make_session()
    user = User(email="caio@example.com", password_hash="x")
    db.add(user)
    db.commit()
    profile = Profile(
        user_id=user.id,
        threshold_hr=185,
        threshold_pace_sec_per_km=280,
        current_weekly_volume_km=30.0,
        goal_mode="health",
        injury_history=[],
        preferred_days=[0, 2, 4, 5],
    )
    db.add(profile)
    when = datetime(2026, 5, 31, 8, 0)
    db.add(
        Activity(
            activity_id=1,
            activity_type="running",
            start_time_local=when,
            start_time_gmt=when,
            distance_km=30.0,
        )
    )
    db.commit()
    yield db, user, profile, compute_constraints(db, profile, MONDAY)
    db.close()


def test_week_generation_stores_a_draft_and_reads_back(seeded):
    db, user, profile, constraints = seeded
    plan = regenerate_plan_week(db, user.id, None, constraints, profile, None, None)
    assert (plan.status, plan.source, plan.notes) == ("draft", "fallback", "")
    assert [w.date for w in plan.workouts] == [s.date for s in constraints.sessions]
    assert get_user_week_plan(db, user.id, MONDAY) is plan
    assert get_user_week_plan(db, user.id, MONDAY + timedelta(weeks=1)) is None


def test_week_regeneration_refuses_non_draft(seeded):
    db, user, profile, constraints = seeded
    plan = regenerate_plan_week(db, user.id, None, constraints, profile, None, None)
    plan.status = "approved"
    with pytest.raises(WeekPlanLockedError, match="already approved"):
        regenerate_plan_week(db, user.id, plan, constraints, profile, None, None)


def test_day_regeneration_errors_without_plan_or_slot(seeded):
    db, user, profile, constraints = seeded
    with pytest.raises(WeekPlanMissingError):
        regenerate_plan_day(db, None, constraints, profile, MONDAY, None, None)
    plan = regenerate_plan_week(db, user.id, None, constraints, profile, None, None)
    tuesday = MONDAY + timedelta(days=1)
    with pytest.raises(SessionSlotMissingError, match=str(tuesday)):
        regenerate_plan_day(db, plan, constraints, profile, tuesday, None, None)


def test_day_regeneration_keeps_notes_and_falls_back(seeded):
    db, user, profile, constraints = seeded
    plan = regenerate_plan_week(db, user.id, None, constraints, profile, "keep", None)
    llm = RejectingLLM()
    plan = regenerate_plan_day(db, plan, constraints, profile, MONDAY, None, llm)
    assert llm.calls == 3
    assert plan.notes == "keep"
    assert plan.validation_errors == []
    assert len(plan.workouts) == len(constraints.sessions)
