"""Duration/distance estimates and step counts for library workouts."""

from app.workouts.estimates import (
    estimated_distance_m,
    estimated_duration_sec,
    executed_step_count,
    step_distance_m,
    step_duration_sec,
)
from app.workouts.schemas import LibraryWorkoutInput
from tests.workout_builders import interval_workout, pace, repeat, step, workout


def items(*raw: dict):
    return LibraryWorkoutInput.model_validate(workout("x", *raw)).steps


def test_time_step_without_pace_has_duration_only():
    (only,) = items(step(end={"type": "time", "seconds": 600}))
    assert step_duration_sec(only) == 600
    assert step_distance_m(only) is None


def test_distance_step_without_pace_has_distance_only():
    (only,) = items(step(end={"type": "distance", "meters": 1000}))
    assert step_distance_m(only) == 1000
    assert step_duration_sec(only) is None


def test_pace_target_derives_the_other_quantity_from_midpoint():
    run_1k, run_10min = items(
        step(end={"type": "distance", "meters": 1000}, target=pace(240, 360)),
        step(end={"type": "time", "seconds": 600}, target=pace(240, 360)),
    )
    assert step_duration_sec(run_1k) == 300
    assert step_distance_m(run_10min) == 2000


def test_lap_button_step_is_unknown():
    (lap,) = items(step(end={"type": "lap_button"}, target=pace(240, 360)))
    assert step_duration_sec(lap) is None
    assert step_distance_m(lap) is None


def test_repeats_multiply_by_iterations():
    parsed = items(
        step(end={"type": "time", "seconds": 600}, target=pace(300, 300 + 1)),
        repeat(
            4,
            step(end={"type": "distance", "meters": 400}, target=pace(240, 260)),
            step(end={"type": "time", "seconds": 90}, target=pace(400, 500)),
        ),
    )
    # 600 + 4 * (400 m @ 250 s/km = 100 s + 90 s)
    assert estimated_duration_sec(parsed) == 600 + 4 * 190
    # 600 s / 300.5 s/km + 4 * (400 + 90 s / 450 s/km)
    assert estimated_distance_m(parsed) == round(600 / 300.5 * 1000 + 4 * 600)


def test_any_unknown_step_nulls_the_total():
    parsed = LibraryWorkoutInput.model_validate(interval_workout()).steps
    assert estimated_duration_sec(parsed) is None
    assert estimated_distance_m(parsed) is None


def test_executed_step_count_expands_repeats():
    parsed = LibraryWorkoutInput.model_validate(interval_workout()).steps
    assert executed_step_count(parsed) == 1 + 4 * 2 + 1
