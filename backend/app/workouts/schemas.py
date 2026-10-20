"""Wire schemas for the workout library (shared contract with the frontend).

Steps use a discriminated union on ``kind`` (``step`` | ``repeat``); a step's
``end`` and ``target`` are discriminated on ``type``. Repeat blocks may only
contain plain steps, so nested repeats fail validation with a 422.
"""

import datetime as dt
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

StepType = Literal["warmup", "run", "recover", "rest", "cooldown"]
MAX_LEAF_STEPS = 100


class TimeEnd(BaseModel):
    type: Literal["time"]
    seconds: int = Field(ge=1, le=86400)


class DistanceEnd(BaseModel):
    type: Literal["distance"]
    meters: int = Field(ge=1, le=100000)


class LapButtonEnd(BaseModel):
    type: Literal["lap_button"]


StepEnd = Annotated[TimeEnd | DistanceEnd | LapButtonEnd, Field(discriminator="type")]


class NoTarget(BaseModel):
    type: Literal["none"]


class HrZoneTarget(BaseModel):
    type: Literal["hr_zone"]
    zone: int = Field(ge=1, le=5)


class HrRangeTarget(BaseModel):
    type: Literal["hr_range"]
    min_bpm: int = Field(ge=30, le=230)
    max_bpm: int = Field(ge=30, le=230)

    @model_validator(mode="after")
    def min_below_max(self) -> Self:
        """Reject inverted or empty HR ranges."""
        if self.min_bpm >= self.max_bpm:
            raise ValueError(
                f"min_bpm={self.min_bpm} must be < max_bpm={self.max_bpm}; "
                "expected {min_bpm: 30..229, max_bpm: min_bpm+1..230}"
            )
        return self


class PaceRangeTarget(BaseModel):
    type: Literal["pace_range"]
    fast_sec_per_km: int = Field(ge=120, le=1200)
    slow_sec_per_km: int = Field(ge=120, le=1200)

    @model_validator(mode="after")
    def fast_below_slow(self) -> Self:
        """The fast pace needs fewer seconds per km than the slow pace."""
        if self.fast_sec_per_km >= self.slow_sec_per_km:
            raise ValueError(
                f"fast_sec_per_km={self.fast_sec_per_km} must be < "
                f"slow_sec_per_km={self.slow_sec_per_km}; expected "
                "{fast_sec_per_km: 120..1199, slow_sec_per_km: fast+1..1200}"
            )
        return self

    @property
    def midpoint_sec_per_km(self) -> float:
        """Average of the two pace bounds, used for estimates."""
        return (self.fast_sec_per_km + self.slow_sec_per_km) / 2


StepTarget = Annotated[
    NoTarget | HrZoneTarget | HrRangeTarget | PaceRangeTarget,
    Field(discriminator="type"),
]


class BuilderStep(BaseModel):
    kind: Literal["step"]
    step_type: StepType
    end: StepEnd
    target: StepTarget
    notes: str = Field(default="", max_length=200)


class RepeatBlock(BaseModel):
    kind: Literal["repeat"]
    iterations: int = Field(ge=2, le=50)
    steps: list[BuilderStep] = Field(min_length=1, max_length=20)


WorkoutItem = Annotated[BuilderStep | RepeatBlock, Field(discriminator="kind")]


def count_defined_steps(items: list[BuilderStep | RepeatBlock]) -> int:
    """Leaf steps as written (each repeat's children counted once).

    Example:
        >>> count_defined_steps([repeat_of_two_steps, single_step])
        3
    """
    return sum(len(i.steps) if isinstance(i, RepeatBlock) else 1 for i in items)


class LibraryWorkoutInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    steps: list[WorkoutItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def leaf_step_limit(self) -> Self:
        """Cap the total number of leaf steps a workout may define."""
        total = count_defined_steps(self.steps)
        if total > MAX_LEAF_STEPS:
            raise ValueError(
                f"workout defines {total} leaf steps; expected at most "
                f"{MAX_LEAF_STEPS} (repeat children counted once)"
            )
        return self


class LibraryWorkoutPushOut(BaseModel):
    date: dt.date
    garmin_workout_id: str
    pushed_at: dt.datetime


class LibraryWorkoutOut(BaseModel):
    id: int
    name: str
    description: str
    steps: list[WorkoutItem]
    estimated_duration_sec: int | None
    estimated_distance_m: int | None
    created_at: dt.datetime
    updated_at: dt.datetime
    pushes: list[LibraryWorkoutPushOut]


class LibraryWorkoutSummaryOut(BaseModel):
    id: int
    name: str
    description: str
    step_count: int
    estimated_duration_sec: int | None
    estimated_distance_m: int | None
    updated_at: dt.datetime


class LibraryWorkoutPushRequest(BaseModel):
    date: dt.date
