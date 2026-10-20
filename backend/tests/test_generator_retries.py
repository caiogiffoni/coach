"""Retry-loop logging and parse-error tests for app/coaching/generator.py."""

import logging
from datetime import date

import pytest
from conftest import make_session

from app.coaching.constraints import compute_constraints
from app.coaching.generator import generate_week, parse_week, parse_workout
from app.profile.models import Profile


class GarbageLLM:
    """Fake LLM that never returns parseable JSON."""

    def generate(self, system: str, user: str) -> str:
        return "no json here"


def test_rejected_llm_answers_are_logged_with_structured_fields(caplog):
    profile = Profile(
        user_id=1,
        current_weekly_volume_km=20.0,
        goal_mode="health",
        injury_history=[],
        preferred_days=[0, 3],
    )
    constraints = compute_constraints(make_session(), profile, date(2026, 6, 1))
    with caplog.at_level(logging.WARNING, logger="app.coaching.generator"):
        result = generate_week(constraints, profile, None, GarbageLLM())
    assert result.source == "fallback"
    records = [r for r in caplog.records if r.message == "LLM response rejected"]
    assert [r.attempt for r in records] == [1, 2, 3]
    assert records[0].error.startswith("Response is not valid JSON")


def test_parse_errors_name_the_expected_schema():
    with pytest.raises(ValueError, match="week schema: workouts"):
        parse_week('{"weeks": []}')
    with pytest.raises(ValueError, match="workout schema"):
        parse_workout('{"name": "x"}')
