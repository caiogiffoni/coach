"""
Bulk import of a Garmin GDPR data export into the normalized SQLite store.

Ported from the pandas loaders in temp/utils.py — same glob patterns, same
wrapper unwrapping, same unit conversions:

  activity distance   cm  → km       (÷ 100_000)
  activity duration   ms  → minutes  (÷ 60_000)
  elevation gain      cm  → m        (÷ 100)
  timestamps          ms epoch → datetime (UTC naive; local kept as wall clock)
  profile weight      g   → kg       (÷ 1_000)
  race predictions    seconds (stored as-is)

Accepts either an extracted export directory (containing DI_CONNECT/) or a
.zip of one. All datasets upsert on natural keys, so re-import is idempotent.
"""

import json
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Activity,
    BiometricProfile,
    DailyWellness,
    Hrv,
    PersonalRecord,
    RacePrediction,
    Sleep,
    TrainingHistory,
    TrainingLoad,
    TrainingReadiness,
    Vo2Max,
)

FITNESS = "DI_CONNECT/DI-Connect-Fitness"
AGGREGATOR = "DI_CONNECT/DI-Connect-Aggregator"
METRICS = "DI_CONNECT/DI-Connect-Metrics"
WELLNESS = "DI_CONNECT/DI-Connect-Wellness"


class ImportReport(BaseModel):
    activities: int = 0
    daily_wellness: int = 0
    sleep: int = 0
    hrv: int = 0
    vo2max: int = 0
    race_predictions: int = 0
    training_load: int = 0
    training_readiness: int = 0
    training_history: int = 0
    personal_records: int = 0
    biometric_profile: int = 0


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ms_to_dt(ms: float | int | None) -> datetime | None:
    """Unix milliseconds → naive UTC datetime."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    """'YYYY-MM-DD' string or epoch-ms int → date."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    return date.fromisoformat(str(value)[:10])


def _parse_pr_date(value: str | None) -> datetime | None:
    """'Sat Sep 20 22:00:00 GMT 2025' → datetime (None if unparseable)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %Z %Y")
    except ValueError:
        return None


def _glob_sorted(base: Path, pattern: str) -> list[Path]:
    return sorted(base.glob(pattern))


# ---------------------------------------------------------------------------
# Upsert helper
# ---------------------------------------------------------------------------


def _upsert_many(
    db: Session,
    model: type,
    key_fields: tuple[str, ...],
    rows: Iterable[dict],
) -> int:
    """Insert or update rows keyed by key_fields. Returns rows processed."""
    rows = list(rows)
    if not rows:
        return 0
    existing = {}
    for obj in db.scalars(select(model)):
        existing[tuple(getattr(obj, k) for k in key_fields)] = obj
    count = 0
    for row in rows:
        key = tuple(row.get(k) for k in key_fields)
        obj = existing.get(key)
        if obj is None:
            obj = model(**row)
            db.add(obj)
            existing[key] = obj
        else:
            for field, value in row.items():
                setattr(obj, field, value)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Dataset loaders (export dir → list of model kwargs)
# ---------------------------------------------------------------------------


def _load_activities(base: Path) -> list[dict]:
    rows = []
    for f in _glob_sorted(base, f"{FITNESS}/*_summarizedActivities.json"):
        for chunk in _read_json(f):
            for a in chunk.get("summarizedActivitiesExport", []):
                if a.get("activityId") is None:
                    continue
                duration = a.get("duration")
                distance = a.get("distance")
                elevation = a.get("elevationGain")
                rows.append({
                    "activity_id": a["activityId"],
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


def _load_daily_wellness(base: Path) -> list[dict]:
    """UDS aggregator rows plus body battery, deduped by date (last wins)."""
    by_date: dict[date, dict] = {}
    for f in _glob_sorted(base, f"{AGGREGATOR}/UDSFile_*.json"):
        for record in _read_json(f):
            cal = _parse_date(record.get("calendarDate"))
            if cal is None:
                continue
            stress = record.get("allDayStress") or {}
            agg_list = stress.get("aggregatorList") or []
            total = next((a for a in agg_list if a.get("type") == "TOTAL"), {})
            bb = record.get("bodyBattery") or {}
            stat_map = {
                s["bodyBatteryStatType"]: s["statsValue"]
                for s in bb.get("bodyBatteryStatList", [])
                if "statsValue" in s
            }
            by_date[cal] = {
                "calendar_date": cal,
                "total_steps": record.get("totalSteps"),
                "daily_step_goal": record.get("dailyStepGoal"),
                "total_distance_m": record.get("totalDistanceMeters"),
                "total_kcal": record.get("totalKilocalories"),
                "active_kcal": record.get("activeKilocalories"),
                "resting_hr": record.get("restingHeartRate"),
                "min_hr": record.get("minHeartRate"),
                "max_hr": record.get("maxHeartRate"),
                "highly_active_seconds": record.get("highlyActiveSeconds"),
                "active_seconds": record.get("activeSeconds"),
                "floors_ascended_m": record.get("floorsAscendedInMeters"),
                "avg_stress": total.get("averageStressLevel"),
                "max_stress": total.get("maxStressLevel"),
                "stress_duration_s": total.get("stressDuration"),
                "rest_duration_s": total.get("restDuration"),
                "bb_charged": bb.get("chargedValue"),
                "bb_drained": bb.get("drainedValue"),
                "bb_highest": stat_map.get("HIGHEST"),
                "bb_lowest": stat_map.get("LOWEST"),
                "bb_start_of_day": stat_map.get("STARTOFDAY"),
                "bb_end_of_day": stat_map.get("ENDOFDAY"),
                "bb_sleep_start": stat_map.get("SLEEPSTART"),
                "bb_sleep_end": stat_map.get("SLEEPEND"),
                "bb_during_sleep": stat_map.get("DURINGSLEEP"),
            }
    return [by_date[d] for d in sorted(by_date)]


def _load_sleep(base: Path) -> list[dict]:
    by_date: dict[date, dict] = {}
    for f in _glob_sorted(base, f"{WELLNESS}/*_sleepData.json"):
        for record in _read_json(f):
            cal = _parse_date(record.get("calendarDate"))
            if cal is None:
                continue
            scores = record.get("sleepScores") or {}
            deep = record.get("deepSleepSeconds") or 0
            light = record.get("lightSleepSeconds") or 0
            rem = record.get("remSleepSeconds") or 0
            by_date[cal] = {
                "calendar_date": cal,
                "sleep_start_gmt": _iso_to_dt(record.get("sleepStartTimestampGMT")),
                "sleep_end_gmt": _iso_to_dt(record.get("sleepEndTimestampGMT")),
                "deep_sleep_s": record.get("deepSleepSeconds"),
                "light_sleep_s": record.get("lightSleepSeconds"),
                "rem_sleep_s": record.get("remSleepSeconds"),
                "awake_sleep_s": record.get("awakeSleepSeconds"),
                "total_sleep_s": deep + light + rem,
                "average_respiration": record.get("averageRespiration"),
                "avg_sleep_stress": record.get("avgSleepStress"),
                "awake_count": record.get("awakeCount"),
                "overall_score": scores.get("overallScore"),
                "quality_score": scores.get("qualityScore"),
                "duration_score": scores.get("durationScore"),
                "recovery_score": scores.get("recoveryScore"),
                "deep_score": scores.get("deepScore"),
                "rem_score": scores.get("remScore"),
                "light_score": scores.get("lightScore"),
                "awakenings_count_score": scores.get("awakeningsCountScore"),
                "combined_awake_score": scores.get("combinedAwakeScore"),
            }
    return [by_date[d] for d in sorted(by_date)]


def _load_hrv(base: Path) -> list[dict]:
    rows = []

    # Health snapshots (RMSSD/SDRR, Apr 2024)
    for f in _glob_sorted(base, f"{WELLNESS}/*_wellnessActivities.json"):
        for rec in _read_json(f):
            cal = _parse_date(rec.get("calendarDate"))
            summary = {s["summaryType"]: s for s in rec.get("summaryTypeDataList", [])}
            rmssd = summary.get("RMSSD_HRV", {}).get("avgValue")
            sdrr = summary.get("SDRR_HRV", {}).get("avgValue")
            if cal is None or (rmssd is None and sdrr is None):
                continue
            rows.append({
                "calendar_date": cal,
                "source": "snapshot",
                "snapshot_time": rec.get("snapshotTimeOfDayType") or "",
                "rmssd": rmssd,
                "sdrr": sdrr,
                "hrv_status": None,
                "hrv_pct": None,
                "baseline_lo": None,
                "baseline_hi": None,
            })

    # Daily health status (Sep 2025+)
    for f in _glob_sorted(base, f"{WELLNESS}/*_healthStatusData.json"):
        for rec in _read_json(f):
            cal = _parse_date(rec.get("calendarDate"))
            metrics = {m["type"]: m for m in rec.get("metrics", [])}
            hrv = metrics.get("HRV", {})
            if cal is None or not hrv.get("value"):
                continue
            rows.append({
                "calendar_date": cal,
                "source": "daily",
                "snapshot_time": "",
                "rmssd": hrv.get("value"),
                "sdrr": None,
                "hrv_status": hrv.get("status"),
                "hrv_pct": hrv.get("percentage"),
                "baseline_lo": hrv.get("baselineLowerLimit"),
                "baseline_hi": hrv.get("baselineUpperLimit"),
            })

    rows.sort(key=lambda r: (r["calendar_date"], r["source"], r["snapshot_time"]))
    return rows


def _load_vo2max(base: Path) -> list[dict]:
    rows = []
    for f in _glob_sorted(base, f"{METRICS}/ActivityVo2Max_*.json"):
        for rec in _read_json(f):
            rows.append({
                "calendar_date": _parse_date(rec.get("calendarDate")),
                "sport": rec.get("sport"),
                "vo2max_value": rec.get("vo2MaxValue"),
                "max_met": None,
                "activity_id": rec.get("activityId"),
                "source": "activity",
            })
    for f in _glob_sorted(base, f"{METRICS}/MetricsMaxMetData_*.json"):
        for rec in _read_json(f):
            rows.append({
                "calendar_date": _parse_date(rec.get("calendarDate")),
                "sport": rec.get("sport"),
                "vo2max_value": rec.get("vo2MaxValue"),
                "max_met": rec.get("maxMet"),
                "activity_id": None,
                "source": "metrics",
            })
    # Dedupe per (date, sport), preferring the "metrics" source on ties
    rows = [r for r in rows if r["calendar_date"] is not None]
    rows.sort(key=lambda r: (r["calendar_date"], r["source"]))
    by_key: dict[tuple, dict] = {}
    for r in rows:
        by_key[(r["calendar_date"], r["sport"])] = r
    return [by_key[k] for k in sorted(by_key, key=lambda k: (k[0], k[1] or ""))]


def _load_race_predictions(base: Path) -> list[dict]:
    by_date: dict[date, dict] = {}
    for f in _glob_sorted(base, f"{METRICS}/RunRacePredictions_*.json"):
        for rec in _read_json(f):
            cal = _parse_date(rec.get("calendarDate"))
            if cal is None:
                continue
            by_date[cal] = {
                "calendar_date": cal,
                "race_time_5k_s": rec.get("raceTime5K"),
                "race_time_10k_s": rec.get("raceTime10K"),
                "race_time_half_s": rec.get("raceTimeHalf"),
                "race_time_marathon_s": rec.get("raceTimeMarathon"),
            }
    return [by_date[d] for d in sorted(by_date)]


def _load_training_load(base: Path) -> list[dict]:
    by_date: dict[date, dict] = {}
    for f in _glob_sorted(base, f"{METRICS}/MetricsAcuteTrainingLoad_*.json"):
        for rec in _read_json(f):
            # calendarDate arrives as epoch ms in this file
            cal = _parse_date(rec.get("calendarDate"))
            if cal is None:
                continue
            by_date[cal] = {
                "calendar_date": cal,
                "acute_load": rec.get("dailyTrainingLoadAcute"),
                "chronic_load": rec.get("dailyTrainingLoadChronic"),
                "acwr": rec.get("dailyAcuteChronicWorkloadRatio"),
                "acwr_status": rec.get("acwrStatus"),
            }
    return [by_date[d] for d in sorted(by_date)]


def _load_training_readiness(base: Path) -> list[dict]:
    by_date: dict[date, dict] = {}
    for f in _glob_sorted(base, f"{METRICS}/TrainingReadinessDTO_*.json"):
        for rec in _read_json(f):
            cal = _parse_date(rec.get("calendarDate"))
            if cal is None:
                continue
            by_date[cal] = {
                "calendar_date": cal,
                "score": rec.get("score"),
                "level": rec.get("level"),
                "feedback_short": rec.get("feedbackShort"),
            }
    return [by_date[d] for d in sorted(by_date)]


def _load_training_history(base: Path) -> list[dict]:
    by_key: dict[tuple, dict] = {}
    for f in _glob_sorted(base, f"{METRICS}/TrainingHistory_*.json"):
        for rec in _read_json(f):
            cal = _parse_date(rec.get("calendarDate"))
            if cal is None:
                continue
            by_key[(cal, rec.get("sport"))] = {
                "calendar_date": cal,
                "sport": rec.get("sport"),
                "training_status": rec.get("trainingStatus"),
                "fitness_level_trend": rec.get("fitnessLevelTrend"),
                "feedback_phrase": rec.get("trainingStatus2FeedbackPhrase"),
            }
    return [by_key[k] for k in sorted(by_key, key=lambda k: (k[0], k[1] or ""))]


def _load_personal_records(base: Path) -> list[dict]:
    rows = []
    for f in _glob_sorted(base, f"{FITNESS}/*_personalRecord.json"):
        for chunk in _read_json(f):
            for pr in chunk.get("personalRecords", []):
                if pr.get("personalRecordId") is None:
                    continue
                rows.append({
                    "personal_record_id": pr["personalRecordId"],
                    "record_type": pr.get("personalRecordType"),
                    "value": pr.get("value"),
                    "pr_start_time_gmt": _parse_pr_date(pr.get("prStartTimeGMT")),
                    "activity_id": pr.get("activityId"),
                    "current": pr.get("current"),
                })
    return rows


def _load_biometric_profile(base: Path) -> dict | None:
    files = _glob_sorted(base, f"{WELLNESS}/*_userBioMetricProfileData.json")
    if not files:
        return None
    data = _read_json(files[-1])
    profile = data[0] if isinstance(data, list) and data else data
    if not isinstance(profile, dict):
        return None
    weight = profile.get("weight")
    return {
        "height_cm": profile.get("height"),
        "weight_kg": weight / 1_000 if weight is not None else None,
        "vo2max": profile.get("vo2Max"),
        "lactate_threshold_hr": profile.get("lactateThresholdHeartRate"),
        "functional_threshold_power": profile.get("functionalThresholdPower"),
        "activity_class": profile.get("activityClass"),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _find_export_root(path: Path) -> Path:
    """Locate the directory that contains DI_CONNECT/ (handles zip nesting)."""
    if (path / "DI_CONNECT").is_dir():
        return path
    for child in sorted(path.iterdir()):
        if child.is_dir() and (child / "DI_CONNECT").is_dir():
            return child
    raise FileNotFoundError(f"No DI_CONNECT directory found under {path}")


def _import_from_root(base: Path, db: Session) -> ImportReport:
    report = ImportReport()
    report.activities = _upsert_many(db, Activity, ("activity_id",), _load_activities(base))
    report.daily_wellness = _upsert_many(
        db, DailyWellness, ("calendar_date",), _load_daily_wellness(base)
    )
    report.sleep = _upsert_many(db, Sleep, ("calendar_date",), _load_sleep(base))
    report.hrv = _upsert_many(
        db, Hrv, ("calendar_date", "source", "snapshot_time"), _load_hrv(base)
    )
    report.vo2max = _upsert_many(db, Vo2Max, ("calendar_date", "sport"), _load_vo2max(base))
    report.race_predictions = _upsert_many(
        db, RacePrediction, ("calendar_date",), _load_race_predictions(base)
    )
    report.training_load = _upsert_many(
        db, TrainingLoad, ("calendar_date",), _load_training_load(base)
    )
    report.training_readiness = _upsert_many(
        db, TrainingReadiness, ("calendar_date",), _load_training_readiness(base)
    )
    report.training_history = _upsert_many(
        db, TrainingHistory, ("calendar_date", "sport"), _load_training_history(base)
    )
    report.personal_records = _upsert_many(
        db, PersonalRecord, ("personal_record_id",), _load_personal_records(base)
    )

    profile = _load_biometric_profile(base)
    if profile is not None:
        obj = db.scalars(select(BiometricProfile)).first()
        if obj is None:
            db.add(BiometricProfile(**profile))
        else:
            for field, value in profile.items():
                setattr(obj, field, value)
        report.biometric_profile = 1

    db.commit()
    return report


def import_export(export_path: Path, db: Session) -> ImportReport:
    """Import a Garmin GDPR export (directory or .zip) into the database."""
    export_path = Path(export_path)
    if not export_path.exists():
        raise FileNotFoundError(f"Export path does not exist: {export_path}")
    if export_path.is_file() and zipfile.is_zipfile(export_path):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(export_path) as zf:
                zf.extractall(tmp)
            return _import_from_root(_find_export_root(Path(tmp)), db)
    return _import_from_root(_find_export_root(export_path), db)
