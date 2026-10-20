"""Duration/distance estimates and step counts for library workouts.

Rules (from the shared contract): time steps contribute their seconds and
distance steps their meters. The other quantity is derived only from a
``pace_range`` target (midpoint pace); otherwise that total is ``None``.
``lap_button`` steps make both totals ``None``. Repeats multiply by iterations.
"""

from collections.abc import Callable

from .schemas import BuilderStep, DistanceEnd, PaceRangeTarget, RepeatBlock, TimeEnd

WorkoutItems = list[BuilderStep | RepeatBlock]
StepMeasure = Callable[[BuilderStep], float | None]


def _midpoint_pace(step: BuilderStep) -> float | None:
    """Midpoint sec/km of the step's pace target, or None without one."""
    if isinstance(step.target, PaceRangeTarget):
        return step.target.midpoint_sec_per_km
    return None


def step_duration_sec(step: BuilderStep) -> float | None:
    """Seconds one step takes, or None when it cannot be estimated.

    Example:
        >>> step_duration_sec(ten_minute_step)
        600
    """
    pace = _midpoint_pace(step)
    if isinstance(step.end, TimeEnd):
        return step.end.seconds
    if isinstance(step.end, DistanceEnd) and pace is not None:
        return step.end.meters / 1000 * pace
    return None


def step_distance_m(step: BuilderStep) -> float | None:
    """Meters one step covers, or None when it cannot be estimated.

    Example:
        >>> step_distance_m(one_km_step)
        1000
    """
    pace = _midpoint_pace(step)
    if isinstance(step.end, DistanceEnd):
        return step.end.meters
    if isinstance(step.end, TimeEnd) and pace is not None:
        return step.end.seconds / pace * 1000
    return None


def _sum_steps(steps: list[BuilderStep], measure: StepMeasure) -> float | None:
    """Sum ``measure`` over ``steps``; None as soon as one step is unknown."""
    total = 0.0
    for step in steps:
        value = measure(step)
        if value is None:
            return None
        total += value
    return total


def _item_total(item: BuilderStep | RepeatBlock, measure: StepMeasure) -> float | None:
    """Measure one item, multiplying a repeat's children by its iterations."""
    if isinstance(item, BuilderStep):
        return measure(item)
    once = _sum_steps(item.steps, measure)
    return None if once is None else once * item.iterations


def _workout_total(items: WorkoutItems, measure: StepMeasure) -> int | None:
    """Rounded total of ``measure`` across all items, or None if any is unknown."""
    total = 0.0
    for item in items:
        value = _item_total(item, measure)
        if value is None:
            return None
        total += value
    return round(total)


def estimated_duration_sec(items: WorkoutItems) -> int | None:
    """Total workout duration in seconds, or None if any step is unknown.

    Example:
        >>> estimated_duration_sec([warmup_10min, repeat_4x_400m_at_pace])
        1080
    """
    return _workout_total(items, step_duration_sec)


def estimated_distance_m(items: WorkoutItems) -> int | None:
    """Total workout distance in meters, or None if any step is unknown.

    Example:
        >>> estimated_distance_m([one_km_step, repeat_4x_400m])
        2600
    """
    return _workout_total(items, step_distance_m)


def executed_step_count(items: WorkoutItems) -> int:
    """Leaf steps the athlete runs, repeats expanded (iterations x children).

    Example:
        >>> executed_step_count([warmup, repeat_4x_two_steps, cooldown])
        10
    """
    return sum(
        len(i.steps) * i.iterations if isinstance(i, RepeatBlock) else 1 for i in items
    )
