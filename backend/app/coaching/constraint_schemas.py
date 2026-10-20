"""
Output schemas of the constraint engine (see constraints.py).

Split out of constraints.py so the state, policy and slot modules can share
one definition without importing the orchestrator.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel

SessionType = Literal["aerobic", "quality", "recovery", "long"]
CycleWeekType = Literal["build", "deload"]
Phase = Literal["base", "build", "peak", "taper", "recovery"]


class WeeklyVolume(BaseModel):
    week_start: date  # Monday of the ISO week
    volume_km: float
    complete: bool  # Sunday of the week is within data coverage


class TrainingState(BaseModel):
    """Snapshot of every metric that drives the constraint decisions."""

    as_of: date | None  # latest date present in the imported data
    weekly_volumes: list[WeeklyVolume]
    avg_weekly_km: float
    last_complete_week_km: float | None
    days_since_last_run: int | None
    days_since_last_hard: int | None
    training_status: str | None  # PRODUCTIVE / MAINTAINING / RECOVERY / …
    acwr: float | None
    acwr_status: str | None
    acute_load: int | None
    chronic_load: int | None
    readiness_score: int | None
    readiness_level: str | None
    hrv_rmssd: float | None
    hrv_status: str | None
    hrv_baseline_lo: float | None
    hrv_baseline_hi: float | None
    resting_hr_latest: int | None
    resting_hr_baseline: float | None  # 30-day median
    sleep_avg_hours_7d: float | None
    sleep_avg_score_7d: float | None


class SessionSlot(BaseModel):
    date: date
    weekday: int  # 0=Mon..6=Sun
    type: SessionType
    distance_km_lo: float
    distance_km_hi: float
    hr_zone_range: str  # e.g. "Z1-Z2"
    hr_bpm_lo: int | None
    hr_bpm_hi: int | None
    pace_zone: str | None  # easy | marathon | threshold | …
    pace_lo_sec_per_km: int | None  # faster bound
    pace_hi_sec_per_km: int | None  # slower bound
    rationale: str


class WeekConstraints(BaseModel):
    """The structure the LLM generator consumes."""

    week_start: date  # Monday of the target week
    goal_mode: str
    phase: Phase | None  # None in health mode (no periodization)
    weeks_to_race: int | None
    cycle_week_type: CycleWeekType
    weekly_volume_target_km: float
    weekly_volume_ceiling_km: float
    intensity_budget_km: float
    allowed_days: list[int]  # weekday ints, 0=Mon
    fatigue_veto: bool
    fatigue_reasons: list[str]
    injury_flags: list[str]  # injury entries matched as restrictive
    sessions: list[SessionSlot]
    state: TrainingState
    rationale: list[str]
