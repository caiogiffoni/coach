"""
Auto-pull recent data from Garmin Connect into the normalized SQLite store.

Uses the dependency-injected ``GarminClient`` protocol so tests can substitute
a fake client. Each dataset is pulled for a configurable look-back window,
transformed into the same kwargs used by ``export_import.py``, and upserted on
its natural key. If a particular Garmin endpoint is unavailable in the
installed ``python-garminconnect`` version, the sync records that in
``SyncReport.skipped_datasets`` instead of crashing.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..garmin.client import GarminClient
from .export_import import _ms_to_dt, _parse_date, _upsert_many
from .models import (
    Activity,
    DailyWellness,
    Hrv,
    TrainingLoad,
    TrainingReadiness,
)

logger = logging.getLogger(__name__)

DEFAULT_DAYS_BACK = 14


class SyncReport(BaseModel):
    """Result of a Garmin Connect auto-pull."""

    activities: int = 0
    daily_wellness: int = 0
    hrv: int = 0
    training_readiness: int = 0
    training_load: int = 0
    skipped_datasets: list[str] = []
    newest_date: date | None = None
    needs_mfa: bool = False


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def latest_local_date(db: Session) -> date | None:
    """Most recent date present across the synced ingestion tables."""
    candidates: list[date] = []
    for model, column in (
        (DailyWellness, DailyWellness.calendar_date),
        (Hrv, Hrv.calendar_date),
        (TrainingLoad, TrainingLoad.calendar_date),
        (TrainingReadiness, TrainingReadiness.calendar_date),
    ):
        latest = db.scalar(select(func.max(column)))
        if latest is not None:
            candidates.append(latest)

    latest_run = db.scalar(select(func.max(Activity.start_time_local)))
    if latest_run is not None:
        candidates.append(latest_run.date())

    return max(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Transformers (Garmin Connect raw dict -> model kwargs)
#
# These are intentionally defensive: Garmin's JSON shape varies by account,
# firmware, and library version. Missing fields become None, which the models
# accept.
# ---------------------------------------------------------------------------


def _transform_activities(raw: list[dict]) -> list[dict]:
    rows = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        activity_id = a.get("activityId")
        if activity_id is None:
            continue
        duration = a.get("duration")
        distance = a.get("distance")
        elevation = a.get("elevationGain")
        rows.append({
            "activity_id": activity_id,
            "name": a.get("name"),
            "activity_type": a.get("activityType"),
            "sport_type": a.get("sportType"),
            "start_time_gmt": _ms_to_dt(a.get("startTimeGmt")),
            "start_time_local": _ms_to_dt(a.get("startTimeLocal")),
            "duration_min": duration / 60_000 if duration is not None else None,
            "distance_km": distance / 100_000 if distance is not None else None,
            "elevation_gain_m": elevation / 100 if elevation is not None else None,
            "avg_hr": a.get("avgHr"),
            "max_hr": a.get("maxHr"),
            "min_hr": a.get("minHr"),
            "calories": a.get("calories"),
            "vo2max_value": a.get("vO2MaxValue"),
            "aerobic_training_effect": a.get("aerobicTrainingEffect"),
            "anaerobic_training_effect": a.get("anaerobicTrainingEffect"),
            "training_load": a.get("activityTrainingLoad"),
            "lap_count": a.get("lapCount"),
            "is_pr": a.get("pr"),
        })
    return rows


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _transform_daily_wellness(raw: list[dict]) -> list[dict]:
    by_date: dict[date, dict] = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        cal = _parse_date(rec.get("calendarDate"))
        if cal is None:
            continue

        # Some Garmin endpoints nest stress data; unwrap common shapes.
        stress = rec.get("allDayStress") or {}
        if not isinstance(stress, dict):
            stress = {}
        agg_list = stress.get("aggregatorList") or []
        total = next((a for a in agg_list if isinstance(a, dict) and a.get("type") == "TOTAL"), {})

        body_battery = rec.get("bodyBattery") or {}
        if not isinstance(body_battery, dict):
            body_battery = {}
        stat_map = {
            s["bodyBatteryStatType"]: s["statsValue"]
            for s in body_battery.get("bodyBatteryStatList", [])
            if isinstance(s, dict) and "statsValue" in s
        }

        by_date[cal] = {
            "calendar_date": cal,
            "total_steps": _to_int(rec.get("totalSteps")),
            "daily_step_goal": _to_int(rec.get("dailyStepGoal")),
            "total_distance_m": rec.get("totalDistanceMeters"),
            "total_kcal": rec.get("totalKilocalories"),
            "active_kcal": rec.get("activeKilocalories"),
            "resting_hr": _to_int(rec.get("restingHeartRate")),
            "min_hr": _to_int(rec.get("minHeartRate")),
            "max_hr": _to_int(rec.get("maxHeartRate")),
            "highly_active_seconds": _to_int(rec.get("highlyActiveSeconds")),
            "active_seconds": _to_int(rec.get("activeSeconds")),
            "floors_ascended_m": rec.get("floorsAscendedInMeters"),
            "avg_stress": _to_int(total.get("averageStressLevel")),
            "max_stress": _to_int(total.get("maxStressLevel")),
            "stress_duration_s": _to_int(total.get("stressDuration")),
            "rest_duration_s": _to_int(total.get("restDuration")),
            "bb_charged": _to_int(body_battery.get("chargedValue")),
            "bb_drained": _to_int(body_battery.get("drainedValue")),
            "bb_highest": _to_int(stat_map.get("HIGHEST")),
            "bb_lowest": _to_int(stat_map.get("LOWEST")),
            "bb_start_of_day": _to_int(stat_map.get("STARTOFDAY")),
            "bb_end_of_day": _to_int(stat_map.get("ENDOFDAY")),
            "bb_sleep_start": _to_int(stat_map.get("SLEEPSTART")),
            "bb_sleep_end": _to_int(stat_map.get("SLEEPEND")),
            "bb_during_sleep": _to_int(stat_map.get("DURINGSLEEP")),
        }
    return [by_date[d] for d in sorted(by_date)]


def _transform_hrv(raw: list[dict]) -> list[dict]:
    rows = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        cal = _parse_date(rec.get("calendarDate"))
        if cal is None:
            continue

        # get_hrv_data may return a nested "hrvSummary" object.
        summary = rec.get("hrvSummary") or rec
        if not isinstance(summary, dict):
            continue

        metrics = {m["type"]: m for m in summary.get("metrics", []) if isinstance(m, dict)}
        hrv = metrics.get("HRV", {})
        if not hrv and summary.get("value"):
            hrv = summary

        rmssd = hrv.get("value") or summary.get("rmssd")
        if rmssd is None:
            continue

        rows.append({
            "calendar_date": cal,
            "source": "daily",
            "snapshot_time": "",
            "rmssd": rmssd,
            "sdrr": summary.get("sdrr"),
            "hrv_status": hrv.get("status") or summary.get("status"),
            "hrv_pct": hrv.get("percentage") or summary.get("percentage"),
            "baseline_lo": hrv.get("baselineLowerLimit") or summary.get("baselineLowerLimit"),
            "baseline_hi": hrv.get("baselineUpperLimit") or summary.get("baselineUpperLimit"),
        })
    return rows


def _transform_training_readiness(raw: list[dict]) -> list[dict]:
    by_date: dict[date, dict] = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        cal = _parse_date(rec.get("calendarDate"))
        if cal is None:
            continue
        by_date[cal] = {
            "calendar_date": cal,
            "score": _to_int(rec.get("score")),
            "level": rec.get("level"),
            "feedback_short": rec.get("feedbackShort"),
        }
    return [by_date[d] for d in sorted(by_date)]


def _transform_training_load(raw: list[dict]) -> list[dict]:
    by_date: dict[date, dict] = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        cal = _parse_date(rec.get("calendarDate"))
        if cal is None:
            continue
        by_date[cal] = {
            "calendar_date": cal,
            "acute_load": _to_int(rec.get("dailyTrainingLoadAcute")),
            "chronic_load": _to_int(rec.get("dailyTrainingLoadChronic")),
            "acwr": rec.get("dailyAcuteChronicWorkloadRatio"),
            "acwr_status": rec.get("acwrStatus"),
        }
    return [by_date[d] for d in sorted(by_date)]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def sync_garmin_data(
    db: Session,
    client: GarminClient,
    days_back: int = DEFAULT_DAYS_BACK,
    as_of: date | None = None,
) -> SyncReport:
    """Pull the last ``days_back`` days from Garmin and upsert locally.

    ``as_of`` defaults to the latest date already present in the local data, or
    ``date.today()`` if the database is empty. This keeps re-syncs idempotent:
    the same wall-clock day is not pulled twice with different ranges.
    """
    if as_of is None:
        as_of = latest_local_date(db) or date.today()
    start_date = as_of - timedelta(days=days_back)
    end_date = as_of

    report = SyncReport()

    # Short-circuit if the client is reporting an MFA challenge.
    if getattr(client, "_pending_mfa", False):
        return SyncReport(needs_mfa=True)

    # --- activities ---
    try:
        raw_activities = client.get_activities(start_date, end_date)
        report.activities = _upsert_many(
            db, Activity, ("activity_id",), _transform_activities(raw_activities)
        )
    except Exception as exc:  # noqa: BLE001 — best-effort dataset
        logger.warning("Sync activities failed: %s", exc)
        report.skipped_datasets.append("activities")

    # --- daily wellness ---
    try:
        raw_wellness = client.get_daily_wellness(start_date, end_date)
        report.daily_wellness = _upsert_many(
            db, DailyWellness, ("calendar_date",), _transform_daily_wellness(raw_wellness)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sync daily_wellness failed: %s", exc)
        report.skipped_datasets.append("daily_wellness")

    # --- HRV ---
    try:
        raw_hrv = client.get_hrv(start_date, end_date)
        report.hrv = _upsert_many(
            db, Hrv, ("calendar_date", "source", "snapshot_time"), _transform_hrv(raw_hrv)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sync hrv failed: %s", exc)
        report.skipped_datasets.append("hrv")

    # --- training readiness ---
    try:
        raw_readiness = client.get_training_readiness(start_date, end_date)
        report.training_readiness = _upsert_many(
            db,
            TrainingReadiness,
            ("calendar_date",),
            _transform_training_readiness(raw_readiness),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sync training_readiness failed: %s", exc)
        report.skipped_datasets.append("training_readiness")

    # --- training load ---
    try:
        raw_load = client.get_training_load(start_date, end_date)
        report.training_load = _upsert_many(
            db, TrainingLoad, ("calendar_date",), _transform_training_load(raw_load)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sync training_load failed: %s", exc)
        report.skipped_datasets.append("training_load")

    db.flush()
    report.newest_date = latest_local_date(db)
    db.commit()
    return report
