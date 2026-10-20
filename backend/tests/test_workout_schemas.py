"""Validation bounds of the workout-library wire schema."""

import pytest
from pydantic import ValidationError

from app.workouts.schemas import (
    LibraryWorkoutInput,
    PaceRangeTarget,
    RepeatBlock,
    count_defined_steps,
)
from tests.workout_builders import interval_workout, pace, repeat, step, workout


def validate(payload: dict) -> LibraryWorkoutInput:
    return LibraryWorkoutInput.model_validate(payload)


def test_valid_interval_workout_parses_discriminated_unions():
    parsed = validate(interval_workout())
    assert isinstance(parsed.steps[1], RepeatBlock)
    assert parsed.steps[1].steps[0].target.type == "pace_range"
    assert parsed.steps[2].end.type == "lap_button"


def test_every_valid_end_and_target_type_parses():
    ends = [
        {"type": "time", "seconds": 1},
        {"type": "distance", "meters": 100000},
        {"type": "lap_button"},
    ]
    targets = [
        {"type": "none"},
        {"type": "hr_zone", "zone": 5},
        {"type": "hr_range", "min_bpm": 30, "max_bpm": 230},
        pace(120, 1200),
    ]
    items = [step("rest", e, t) for e in ends for t in targets]
    assert len(validate(workout("All", *items)).steps) == 12


def test_notes_default_to_empty():
    raw = step()
    del raw["notes"]
    assert validate(workout("x", raw)).steps[0].notes == ""


@pytest.mark.parametrize(
    "bad_step",
    [
        step(end={"type": "time", "seconds": 0}),
        step(end={"type": "time", "seconds": 86401}),
        step(end={"type": "time", "seconds": 10.5}),
        step(end={"type": "distance", "meters": 0}),
        step(end={"type": "distance", "meters": 100001}),
        step(end={"type": "calories", "kcal": 10}),
        step(target={"type": "hr_zone", "zone": 0}),
        step(target={"type": "hr_zone", "zone": 6}),
        step(target={"type": "hr_range", "min_bpm": 29, "max_bpm": 150}),
        step(target={"type": "hr_range", "min_bpm": 120, "max_bpm": 231}),
        step(target={"type": "hr_range", "min_bpm": 150, "max_bpm": 150}),
        step(target=pace(119, 300)),
        step(target=pace(240, 1201)),
        step(target=pace(300, 240)),
        step(step_type="sprint"),
        step(notes="x" * 201),
    ],
)
def test_step_bounds_are_rejected(bad_step):
    with pytest.raises(ValidationError):
        validate(workout("x", bad_step))


@pytest.mark.parametrize(
    "bad_item",
    [
        repeat(1, step()),
        repeat(51, step()),
        repeat(2),
        repeat(2, *[step()] * 21),
        repeat(2, repeat(2, step())),
    ],
)
def test_repeat_bounds_are_rejected(bad_item):
    with pytest.raises(ValidationError):
        validate(workout("x", bad_item))


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "n" * 101},
        {"description": "d" * 1001},
        {"steps": []},
        {"steps": [step()] * 51},
        {"steps": [repeat(2, *[step()] * 20)] * 5 + [step()]},
    ],
)
def test_workout_bounds_are_rejected(overrides):
    with pytest.raises(ValidationError):
        validate({**workout("x"), **overrides})


def test_hundred_leaf_steps_is_allowed():
    payload = {**workout("x"), "steps": [repeat(50, *[step()] * 20)] * 5}
    assert count_defined_steps(validate(payload).steps) == 100


def test_inverted_hr_range_error_names_values():
    with pytest.raises(ValidationError, match="min_bpm=160 must be < max_bpm=150"):
        validate(
            workout(
                "x", step(target={"type": "hr_range", "min_bpm": 160, "max_bpm": 150})
            )
        )


def test_pace_midpoint():
    target = PaceRangeTarget(
        type="pace_range", fast_sec_per_km=240, slow_sec_per_km=260
    )
    assert target.midpoint_sec_per_km == 250
