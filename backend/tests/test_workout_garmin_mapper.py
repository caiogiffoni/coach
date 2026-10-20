"""Library workout -> Garmin Connect workout JSON mapping."""

from itertools import count

import pytest
from garminconnect.workout import RunningWorkout

from app.workouts.garmin_mapper import (
    end_condition_fields,
    executable_step,
    garmin_steps,
    library_workout_to_garmin_json,
    pace_to_speed_mps,
    repeat_group,
    target_fields,
)
from app.workouts.schemas import LibraryWorkoutInput
from tests.workout_builders import interval_workout, pace, step, workout


def parse(payload: dict) -> LibraryWorkoutInput:
    return LibraryWorkoutInput.model_validate(payload)


def single(raw_step: dict):
    return parse(workout("x", raw_step)).steps[0]


def test_pace_to_speed_conversion():
    assert pace_to_speed_mps(300) == 3.3333
    assert pace_to_speed_mps(250) == 4.0


def test_pace_to_speed_rejects_non_positive():
    with pytest.raises(ValueError, match="sec_per_km=0"):
        pace_to_speed_mps(0)


@pytest.mark.parametrize(
    ("end", "key", "type_id", "value"),
    [
        ({"type": "time", "seconds": 600}, "time", 2, 600.0),
        ({"type": "distance", "meters": 400}, "distance", 3, 400.0),
        ({"type": "lap_button"}, "lap.button", 1, None),
    ],
)
def test_end_conditions(end, key, type_id, value):
    fields = end_condition_fields(single(step(end=end)).end)
    assert fields["endCondition"]["conditionTypeKey"] == key
    assert fields["endCondition"]["conditionTypeId"] == type_id
    assert fields["endConditionValue"] == value


def test_no_target():
    fields = target_fields(single(step()).target)
    assert fields["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert fields["zoneNumber"] is None


def test_hr_zone_target_uses_zone_number():
    fields = target_fields(single(step(target={"type": "hr_zone", "zone": 3})).target)
    assert fields["targetType"]["workoutTargetTypeId"] == 4
    assert fields["zoneNumber"] == 3
    assert fields["targetValueOne"] is None


def test_hr_range_target_uses_bpm_bounds():
    raw = {"type": "hr_range", "min_bpm": 140, "max_bpm": 155}
    fields = target_fields(single(step(target=raw)).target)
    assert fields["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (fields["targetValueOne"], fields["targetValueTwo"]) == (140, 155)
    assert fields["zoneNumber"] is None


def test_pace_target_is_speed_with_faster_pace_as_higher_value():
    fields = target_fields(single(step(target=pace(250, 300))).target)
    assert fields["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert fields["targetType"]["workoutTargetTypeId"] == 6
    assert fields["targetValueOne"] == 3.3333  # slow 5:00/km
    assert fields["targetValueTwo"] == 4.0  # fast 4:10/km


@pytest.mark.parametrize(
    ("step_type", "type_id", "type_key"),
    [
        ("warmup", 1, "warmup"),
        ("cooldown", 2, "cooldown"),
        ("run", 3, "interval"),
        ("recover", 4, "recovery"),
        ("rest", 5, "rest"),
    ],
)
def test_step_types(step_type, type_id, type_key):
    mapped = executable_step(single(step(step_type)), 1, None)
    assert mapped["stepType"]["stepTypeId"] == type_id
    assert mapped["stepType"]["stepTypeKey"] == type_key


def test_step_notes_go_to_description():
    assert (
        executable_step(single(step(notes="relax")), 1, None)["description"] == "relax"
    )
    assert executable_step(single(step()), 1, None)["description"] is None


def test_repeat_group_and_step_order_across_workout():
    steps = garmin_steps(parse(interval_workout()).steps)
    warmup, group, cooldown = steps
    assert [warmup["stepOrder"], group["stepOrder"], cooldown["stepOrder"]] == [1, 2, 5]
    assert group["type"] == "RepeatGroupDTO"
    assert group["numberOfIterations"] == 4
    assert group["endConditionValue"] == 4.0
    assert group["endCondition"]["conditionTypeKey"] == "iterations"
    assert [c["stepOrder"] for c in group["workoutSteps"]] == [3, 4]
    assert {c["childStepId"] for c in group["workoutSteps"]} == {group["childStepId"]}
    assert warmup["childStepId"] is None


def test_repeat_group_consumes_its_own_order_first():
    block = parse(interval_workout()).steps[1]
    group = repeat_group(block, count(7), child_step_id=2)
    assert group["stepOrder"] == 7
    assert group["childStepId"] == 2
    assert [c["stepOrder"] for c in group["workoutSteps"]] == [8, 9]


def test_full_workout_json_is_accepted_by_library_model():
    body = library_workout_to_garmin_json(parse(interval_workout("Track")))
    assert body["workoutName"] == "Track"
    assert body["sportType"]["sportTypeKey"] == "running"
    assert len(body["workoutSegments"]) == 1
    # Structural check against garminconnect's own typed workout models.
    RunningWorkout.model_validate(body)


def test_estimated_duration_falls_back_to_zero_when_unknown():
    body = library_workout_to_garmin_json(parse(interval_workout()))
    assert body["estimatedDurationInSecs"] == 0
    timed = library_workout_to_garmin_json(parse(workout("x", step())))
    assert timed["estimatedDurationInSecs"] == 600
