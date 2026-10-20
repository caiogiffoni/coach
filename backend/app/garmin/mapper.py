"""Map app ``Workout`` rows to Garmin Connect workout JSON.

The output follows the unofficial Garmin workout-service schema used by
``garminconnect.Garmin.upload_workout``. Steps are time-based (matching the
app's ``duration_min`` fields) and HR targets are expressed as zone numbers
(Z1–Z5) per PLAN.md step 7.
"""

from ..coaching.plan_models import Workout

SPORT_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
EQUIP_NONE = {"equipmentTypeId": 0, "displayOrder": 0}

TARGET_NONE = {
    "workoutTargetTypeId": 1,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}

END_TIME = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayable": True,
    "displayOrder": 2,
}

_STEP_TYPE_MAP = {
    "warmup": (1, "warmup"),
    "main": (3, "interval"),
    "interval": (3, "interval"),
    "recovery": (4, "recovery"),
    # Garmin's rest stepTypeId is 5 (garminconnect.workout.StepType.REST);
    # it was previously sent as 4, which is recovery.
    "rest": (5, "rest"),
    "cooldown": (2, "cooldown"),
}


def _hr_zone_target(zone_label: str) -> dict:
    """Convert a zone label like Z1/Z2 into a Garmin HR-zone target.

    Note: Garmin's ``heart.rate.zone`` target normally carries BPM bounds. We
    use the zone index (1–5) for both bounds, matching the simplified schema
    requested in PLAN.md step 7. This has not been validated against a real
    device yet; adjust to BPM bounds once profile zone resolution is wired in.
    """
    zone_number = int(zone_label.lstrip("Z"))
    return {
        "workoutTargetTypeId": 4,
        "workoutTargetTypeKey": "heart.rate.zone",
        "displayOrder": 1,
        "targetValueOne": zone_number,
        "targetValueTwo": zone_number,
    }


def _step(
    step_order: int,
    step_type_id: int,
    step_type_key: str,
    duration_seconds: float,
    target: dict,
) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepId": None,
        "stepOrder": step_order,
        "childStepId": 1,
        "description": None,
        "stepType": {
            "stepTypeId": step_type_id,
            "stepTypeKey": step_type_key,
            "displayOrder": step_type_id,
        },
        "endCondition": END_TIME,
        "endConditionValue": duration_seconds,
        "targetType": target,
        "equipmentType": EQUIP_NONE,
    }


def _segment(steps: list[dict]) -> dict:
    return {
        "segmentOrder": 1,
        "sportType": SPORT_RUNNING,
        "workoutSteps": steps,
    }


def workout_to_garmin_json(workout: Workout) -> dict:
    """Convert a stored ``Workout`` into Garmin's workout JSON body."""
    steps: list[dict] = []
    for i, step in enumerate(workout.steps, start=1):
        type_id, type_key = _STEP_TYPE_MAP.get(
            step.get("type", "main").lower(), (3, "interval")
        )
        target = TARGET_NONE
        zone = step.get("target_zone")
        if zone:
            target = _hr_zone_target(zone)
        steps.append(
            _step(
                step_order=i,
                step_type_id=type_id,
                step_type_key=type_key,
                duration_seconds=round(step.get("duration_min", 0) * 60),
                target=target,
            )
        )

    return {
        "workoutId": None,
        "ownerId": None,
        "workoutName": workout.name,
        "description": workout.description,
        "sportType": SPORT_RUNNING,
        "workoutSegments": [_segment(steps)],
        "poolLength": 25.0,
        "shared": False,
    }
