from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sport_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_time_gmt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    start_time_local: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    aerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    lap_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_pr: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class DailyWellness(Base):
    """UDS aggregator row: steps/HR/stress plus body battery for the day."""

    __tablename__ = "daily_wellness"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_step_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    highly_active_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    floors_ascended_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rest_duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Body battery (0–100), present from Apr 2024 onward
    bb_charged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_drained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_highest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_lowest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_start_of_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_end_of_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_sleep_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_sleep_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_during_sleep: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Sleep(Base):
    __tablename__ = "sleep"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    sleep_start_gmt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sleep_end_gmt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deep_sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_respiration: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_sleep_stress: Mapped[float | None] = mapped_column(Float, nullable=True)
    awake_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Scores only present from Apr 2024 onward
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awakenings_count_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    combined_awake_score: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Hrv(Base):
    """HRV readings. source="snapshot" (wellnessActivities) or "daily" (healthStatusData)."""

    __tablename__ = "hrv"
    __table_args__ = (UniqueConstraint("calendar_date", "source", "snapshot_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(20))
    snapshot_time: Mapped[str] = mapped_column(String(20), default="")  # "" for daily rows
    rmssd: Mapped[float | None] = mapped_column(Float, nullable=True)
    sdrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hrv_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_lo: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_hi: Mapped[float | None] = mapped_column(Float, nullable=True)


class Vo2Max(Base):
    __tablename__ = "vo2max"
    __table_args__ = (UniqueConstraint("calendar_date", "sport"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, index=True)
    sport: Mapped[str | None] = mapped_column(String(30), nullable=True)
    vo2max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_met: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # "activity" | "metrics"


class RacePrediction(Base):
    __tablename__ = "race_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    race_time_5k_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_time_10k_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_time_half_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_time_marathon_s: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TrainingLoad(Base):
    """Acute/chronic training load (ACWR)."""

    __tablename__ = "training_load"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    acute_load: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chronic_load: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acwr: Mapped[float | None] = mapped_column(Float, nullable=True)
    acwr_status: Mapped[str | None] = mapped_column(String(30), nullable=True)


class TrainingReadiness(Base):
    __tablename__ = "training_readiness"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    feedback_short: Mapped[str | None] = mapped_column(String(100), nullable=True)


class TrainingHistory(Base):
    __tablename__ = "training_history"
    __table_args__ = (UniqueConstraint("calendar_date", "sport"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, index=True)
    sport: Mapped[str | None] = mapped_column(String(30), nullable=True)
    training_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fitness_level_trend: Mapped[str | None] = mapped_column(String(30), nullable=True)
    feedback_phrase: Mapped[str | None] = mapped_column(String(50), nullable=True)


class PersonalRecord(Base):
    __tablename__ = "personal_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    personal_record_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    record_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # seconds or cm
    pr_start_time_gmt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class BiometricProfile(Base):
    """Single-row snapshot of the athlete's biometric profile."""

    __tablename__ = "biometric_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    lactate_threshold_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    functional_threshold_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_class: Mapped[int | None] = mapped_column(Integer, nullable=True)
