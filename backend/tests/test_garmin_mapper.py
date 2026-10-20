"""Mapper unit tests — no DB, no Garmin API calls."""

from datetime import date

import pytest

from app.coaching.plan_models import Workout
from app.garmin.mapper import _STEP_TYPE_MAP, workout_to_garmin_json


def _workout(name: str, steps: list[dict], description: str = "") -> Workout:
    return Workout(
        id=1,
        week_plan_id=1,
        date=date(2026, 5, 11),
        name=name,
        sport="running",
        duration_min=45.0,
        description=description,
        steps=steps,
        slot_type="aerobic",
        status="planned",
    )


def _step_payload(
    step_type: str,
    duration_min: float,
    target_zone: str | None = None,
    **extra,
) -> dict:
    return {
        "type": step_type,
        "duration_min": duration_min,
        "target_zone": target_zone,
        "target_pace_min": None,
        "target_pace_max": None,
        "target_hr_min": None,
        "target_hr_max": None,
        **extra,
    }


def test_full_workout_maps_name_sport_and_description():
    wo = _workout(
        "Z2 Easy Run",
        [_step_payload("warmup", 10.0, "Z1"), _step_payload("main", 35.0, "Z2")],
        description="Aerobic base run",
    )
    payload = workout_to_garmin_json(wo)

    assert payload["workoutName"] == "Z2 Easy Run"
    assert payload["description"] == "Aerobic base run"
    assert payload["sportType"]["sportTypeKey"] == "running"
    assert payload["sportType"]["sportTypeId"] == 1
    assert len(payload["workoutSegments"]) == 1


def test_step_types_and_durations():
    wo = _workout(
        "Intervals",
        [
            _step_payload("warmup", 10.0, "Z1"),
            _step_payload("interval", 1.0, "Z5"),
            _step_payload("recovery", 2.0, "Z1"),
            _step_payload("rest", 1.5),
            _step_payload("cooldown", 5.0, "Z1"),
            _step_payload("main", 20.0, "Z3"),
        ],
    )
    payload = workout_to_garmin_json(wo)
    steps = payload["workoutSegments"][0]["workoutSteps"]

    assert len(steps) == 6
    assert steps[0]["stepType"]["stepTypeKey"] == "warmup"
    assert steps[1]["stepType"]["stepTypeKey"] == "interval"
    assert steps[2]["stepType"]["stepTypeKey"] == "recovery"
    assert steps[3]["stepType"]["stepTypeKey"] == "rest"
    # Regression: rest used to be sent with recovery's id (4).
    assert steps[3]["stepType"]["stepTypeId"] == 5
    assert steps[4]["stepType"]["stepTypeKey"] == "cooldown"
    assert steps[5]["stepType"]["stepTypeKey"] == "interval"  # main maps to interval

    assert steps[0]["endConditionValue"] == 600
    assert steps[1]["endConditionValue"] == 60
    assert steps[2]["endConditionValue"] == 120
    assert steps[3]["endConditionValue"] == 90
    assert steps[4]["endConditionValue"] == 300
    assert steps[5]["endConditionValue"] == 1200


def test_hr_zone_targets():
    wo = _workout(
        "Zones",
        [
            _step_payload("main", 10.0, "Z1"),
            _step_payload("main", 10.0, "Z2"),
            _step_payload("main", 10.0, "Z5"),
        ],
    )
    steps = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"]

    for zone_number, step in zip([1, 2, 5], steps, strict=True):
        target = step["targetType"]
        assert target["workoutTargetTypeKey"] == "heart.rate.zone"
        assert target["targetValueOne"] == zone_number
        assert target["targetValueTwo"] == zone_number


def test_missing_target_zone_uses_no_target():
    wo = _workout("No zone", [_step_payload("main", 30.0)])
    step = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"][0]

    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_target_hr_without_zone_ignored():
    """The mapper only looks at target_zone; HR bounds alone don't create a target."""
    wo = _workout(
        "HR only",
        [
            {
                "type": "main",
                "duration_min": 20.0,
                "target_zone": None,
                "target_pace_min": None,
                "target_pace_max": None,
                "target_hr_min": 150,
                "target_hr_max": 165,
            }
        ],
    )
    step = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"][0]

    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_unknown_step_type_defaults_to_interval():
    wo = _workout("Weird type", [_step_payload("spin", 10.0, "Z2")])
    step = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"][0]

    assert step["stepType"]["stepTypeKey"] == "interval"
    assert step["stepType"]["stepTypeId"] == 3


def test_step_type_keys_are_lowercased():
    wo = _workout(
        "Mixed case",
        [_step_payload("WARMUP", 10.0, "Z1"), _step_payload("COOLDOWN", 5.0, "Z1")],
    )
    steps = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"]

    assert steps[0]["stepType"]["stepTypeKey"] == "warmup"
    assert steps[1]["stepType"]["stepTypeKey"] == "cooldown"


def test_empty_steps_yields_empty_segment():
    wo = _workout("Rest", [])
    payload = workout_to_garmin_json(wo)

    assert payload["workoutSegments"][0]["workoutSteps"] == []


def test_duration_seconds_rounded():
    wo = _workout("Odd duration", [_step_payload("main", 10.5, "Z2")])
    step = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"][0]

    assert step["endConditionValue"] == 630  # 10.5 * 60


def test_step_order_starts_at_one():
    wo = _workout("Ordered", [_step_payload("warmup", 5), _step_payload("main", 20)])
    steps = workout_to_garmin_json(wo)["workoutSegments"][0]["workoutSteps"]

    assert steps[0]["stepOrder"] == 1
    assert steps[1]["stepOrder"] == 2


def test_lowercase_zone_label_raises():
    """Current mapper expects uppercase Z1-Z5; guard the documented contract."""
    wo = _workout("Bad zone", [_step_payload("main", 10.0, "z2")])

    with pytest.raises(ValueError):
        workout_to_garmin_json(wo)


def test_step_type_map_coverage():
    """Ensure every documented type has an entry so new code doesn't silently fall back."""
    assert _STEP_TYPE_MAP["warmup"] == (1, "warmup")
    assert _STEP_TYPE_MAP["main"] == (3, "interval")
    assert _STEP_TYPE_MAP["interval"] == (3, "interval")
    assert _STEP_TYPE_MAP["recovery"] == (4, "recovery")
    assert _STEP_TYPE_MAP["rest"] == (5, "rest")
    assert _STEP_TYPE_MAP["cooldown"] == (2, "cooldown")
