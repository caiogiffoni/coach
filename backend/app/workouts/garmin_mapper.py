"""Map library workouts to Garmin Connect workout JSON.

Targets the unofficial workout-service schema that
``garminconnect.Garmin.upload_workout`` posts. Shared constants (sport type,
equipment, no-target, time end condition, segment shape) are reused from
``app.garmin.mapper`` so both pushes stay consistent.

Verified against the installed ``garminconnect`` source (``workout.py``):
  * step type ids: warmup=1, cooldown=2, interval=3, recovery=4, rest=5,
    repeat=6 (``StepType``);
  * end condition ids: lap.button=1, time=2, distance=3, iterations=7
    (``ConditionType``);
  * target type ids: no.target=1, heart.rate.zone=4, pace.zone=6
    (``TargetType``);
  * ``ExecutableStepDTO`` / ``RepeatGroupDTO`` field names (``stepOrder``,
    ``stepType``, ``endCondition``, ``endConditionValue``, ``targetType``,
    ``numberOfIterations``, ``workoutSteps``, ``smartRepeat``,
    ``childStepId``) and the repeat group's iterations end condition with
    ``endConditionValue`` = iterations (``create_repeat_group``).

Assumed from Garmin Connect web-app payloads (not in the library source):
  * HR zone targets carry ``zoneNumber``; custom HR ranges carry bpm in
    ``targetValueOne`` (low) / ``targetValueTwo`` (high) with the same
    ``heart.rate.zone`` target type;
  * pace targets carry speed in m/s with ``targetValueOne`` the slower
    (lower) speed and ``targetValueTwo`` the faster (higher) speed;
  * lap-button steps send ``endConditionValue: null``; distances are meters;
  * ``childStepId`` is the 1-based index of the enclosing repeat group (null
    for top-level steps); step notes go in ``description``.
"""

from collections.abc import Iterator
from itertools import count

from garminconnect.workout import ConditionType, StepType, TargetType

from ..garmin.mapper import END_TIME, EQUIP_NONE, SPORT_RUNNING, TARGET_NONE, _segment
from .estimates import estimated_duration_sec
from .schemas import (
    BuilderStep,
    DistanceEnd,
    HrRangeTarget,
    HrZoneTarget,
    LapButtonEnd,
    LibraryWorkoutInput,
    NoTarget,
    PaceRangeTarget,
    RepeatBlock,
    TimeEnd,
)

_STEP_TYPES: dict[str, tuple[int, str]] = {
    "warmup": (StepType.WARMUP, "warmup"),
    "run": (StepType.INTERVAL, "interval"),
    "recover": (StepType.RECOVERY, "recovery"),
    "rest": (StepType.REST, "rest"),
    "cooldown": (StepType.COOLDOWN, "cooldown"),
}
END_DISTANCE = {
    "conditionTypeId": ConditionType.DISTANCE,
    "conditionTypeKey": "distance",
    "displayable": True,
    "displayOrder": ConditionType.DISTANCE,
}
END_LAP_BUTTON = {
    "conditionTypeId": ConditionType.LAP_BUTTON,
    "conditionTypeKey": "lap.button",
    "displayable": True,
    "displayOrder": ConditionType.LAP_BUTTON,
}
END_ITERATIONS = {
    "conditionTypeId": ConditionType.ITERATIONS,
    "conditionTypeKey": "iterations",
    "displayable": False,
    "displayOrder": ConditionType.ITERATIONS,
}
TARGET_HR_ZONE = {
    "workoutTargetTypeId": TargetType.HEART_RATE_ZONE,
    "workoutTargetTypeKey": "heart.rate.zone",
    "displayOrder": TargetType.HEART_RATE_ZONE,
}
TARGET_PACE_ZONE = {
    "workoutTargetTypeId": TargetType.PACE_ZONE,
    "workoutTargetTypeKey": "pace.zone",
    "displayOrder": TargetType.PACE_ZONE,
}
REPEAT_STEP_TYPE = {
    "stepTypeId": StepType.REPEAT,
    "stepTypeKey": "repeat",
    "displayOrder": StepType.REPEAT,
}


def pace_to_speed_mps(sec_per_km: float) -> float:
    """Convert a pace in seconds per km to a speed in metres per second.

    Example:
        >>> pace_to_speed_mps(300)
        3.3333
    """
    if sec_per_km <= 0:
        raise ValueError(f"sec_per_km={sec_per_km!r}; expected a positive number")
    return round(1000 / sec_per_km, 4)


def end_condition_fields(end: TimeEnd | DistanceEnd | LapButtonEnd) -> dict:
    """Garmin ``endCondition`` + ``endConditionValue`` for a builder end.

    Example:
        >>> end_condition_fields(TimeEnd(type="time", seconds=600))["endConditionValue"]
        600.0
    """
    if isinstance(end, TimeEnd):
        return {"endCondition": END_TIME, "endConditionValue": float(end.seconds)}
    if isinstance(end, DistanceEnd):
        return {"endCondition": END_DISTANCE, "endConditionValue": float(end.meters)}
    return {"endCondition": END_LAP_BUTTON, "endConditionValue": None}


def _target(
    target_type: dict, low: float | None = None, high: float | None = None
) -> dict:
    """Target fields with optional value bounds and no zone number."""
    return {
        "targetType": target_type,
        "targetValueOne": low,
        "targetValueTwo": high,
        "zoneNumber": None,
    }


def target_fields(
    target: NoTarget | HrZoneTarget | HrRangeTarget | PaceRangeTarget,
) -> dict:
    """Garmin target fields (type, bounds, zone number) for a builder target.

    Example:
        >>> target_fields(HrZoneTarget(type="hr_zone", zone=2))["zoneNumber"]
        2
    """
    if isinstance(target, HrZoneTarget):
        return {**_target(TARGET_HR_ZONE), "zoneNumber": target.zone}
    if isinstance(target, HrRangeTarget):
        return _target(TARGET_HR_ZONE, target.min_bpm, target.max_bpm)
    if isinstance(target, PaceRangeTarget):
        slow = pace_to_speed_mps(target.slow_sec_per_km)
        return _target(
            TARGET_PACE_ZONE, slow, pace_to_speed_mps(target.fast_sec_per_km)
        )
    return _target(TARGET_NONE)


def executable_step(
    step: BuilderStep, step_order: int, child_step_id: int | None
) -> dict:
    """One ``ExecutableStepDTO`` for a builder step.

    Example:
        >>> executable_step(warmup_step, step_order=1, child_step_id=None)["type"]
        'ExecutableStepDTO'
    """
    type_id, type_key = _STEP_TYPES[step.step_type]
    return {
        "type": "ExecutableStepDTO",
        "stepId": None,
        "stepOrder": step_order,
        "childStepId": child_step_id,
        "description": step.notes or None,
        "stepType": {
            "stepTypeId": type_id,
            "stepTypeKey": type_key,
            "displayOrder": type_id,
        },
        **end_condition_fields(step.end),
        **target_fields(step.target),
        "equipmentType": EQUIP_NONE,
    }


def repeat_group(
    block: RepeatBlock, step_orders: Iterator[int], child_step_id: int
) -> dict:
    """One ``RepeatGroupDTO``; consumes step orders for itself then its children.

    Example:
        >>> repeat_group(four_by_400m, count(2), child_step_id=1)["numberOfIterations"]
        4
    """
    group_order = next(step_orders)
    children = [
        executable_step(s, next(step_orders), child_step_id) for s in block.steps
    ]
    return {
        "type": "RepeatGroupDTO",
        "stepId": None,
        "stepOrder": group_order,
        "childStepId": child_step_id,
        "stepType": REPEAT_STEP_TYPE,
        "numberOfIterations": block.iterations,
        "smartRepeat": False,
        "endCondition": END_ITERATIONS,
        "endConditionValue": float(block.iterations),
        "workoutSteps": children,
    }


def garmin_steps(items: list[BuilderStep | RepeatBlock]) -> list[dict]:
    """Garmin step list with ``stepOrder`` numbered across the whole workout.

    Example:
        >>> [s["stepOrder"] for s in garmin_steps([warmup, four_by_400m])]
        [1, 2]
    """
    step_orders, repeat_ids = count(1), count(1)
    steps: list[dict] = []
    for item in items:
        if isinstance(item, RepeatBlock):
            steps.append(repeat_group(item, step_orders, next(repeat_ids)))
        else:
            steps.append(executable_step(item, next(step_orders), None))
    return steps


def library_workout_to_garmin_json(workout: LibraryWorkoutInput) -> dict:
    """Full Garmin workout body for ``Garmin.upload_workout``.

    Example:
        >>> library_workout_to_garmin_json(payload)["workoutName"]
        'Tuesday intervals'
    """
    return {
        "workoutId": None,
        "ownerId": None,
        "workoutName": workout.name,
        "description": workout.description or None,
        "sportType": SPORT_RUNNING,
        "estimatedDurationInSecs": estimated_duration_sec(workout.steps) or 0,
        "workoutSegments": [_segment(garmin_steps(workout.steps))],
        "shared": False,
    }
