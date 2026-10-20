"""GDPR export loaders for activity, wellness, sleep, HRV and profile data.

Each loader turns the export directory into a list of model kwargs; the
orchestrator in ``export_import`` upserts them.
"""

from datetime import date
from pathlib import Path
from typing import Any

from .export_parsing import (
    AGGREGATOR,
    FITNESS,
    WELLNESS,
    _glob_sorted,
    _iso_to_dt,
    _iter_json_records,
    _parse_date,
    _parse_pr_date,
    _read_json,
    _scale,
    _sorted_by_date,
    activity_row,
)


def _load_activities(base: Path) -> list[dict]:
    rows = []
    for chunk in _iter_json_records(base, f"{FITNESS}/*_summarizedActivities.json"):
        for a in chunk.get("summarizedActivitiesExport", []):
            if a.get("activityId") is None:
                continue
            rows.append(activity_row(a))
    return rows


def _total_stress(record: dict) -> dict[str, Any]:
    """The TOTAL entry of the all-day stress aggregator list (or {})."""
    stress = record.get("allDayStress") or {}
    agg_list = stress.get("aggregatorList") or []
    return next((a for a in agg_list if a.get("type") == "TOTAL"), {})


def _body_battery_stats(bb: dict) -> dict[str, Any]:
    """Map bodyBatteryStatType → statsValue for entries that carry a value."""
    return {
        s["bodyBatteryStatType"]: s["statsValue"]
        for s in bb.get("bodyBatteryStatList", [])
        if "statsValue" in s
    }


def _wellness_activity_fields(record: dict) -> dict[str, Any]:
    return {
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
    }


def _wellness_stress_fields(total: dict[str, Any]) -> dict[str, Any]:
    return {
        "avg_stress": total.get("averageStressLevel"),
        "max_stress": total.get("maxStressLevel"),
        "stress_duration_s": total.get("stressDuration"),
        "rest_duration_s": total.get("restDuration"),
    }


def _wellness_body_battery_fields(bb: dict) -> dict[str, Any]:
    stat_map = _body_battery_stats(bb)
    return {
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


def _daily_wellness_row(cal: date, record: dict) -> dict:
    return {
        "calendar_date": cal,
        **_wellness_activity_fields(record),
        **_wellness_stress_fields(_total_stress(record)),
        **_wellness_body_battery_fields(record.get("bodyBattery") or {}),
    }


def _load_daily_wellness(base: Path) -> list[dict]:
    """UDS aggregator rows plus body battery, deduped by date (last wins)."""
    by_date: dict[date, dict] = {}
    for record in _iter_json_records(base, f"{AGGREGATOR}/UDSFile_*.json"):
        cal = _parse_date(record.get("calendarDate"))
        if cal is None:
            continue
        by_date[cal] = _daily_wellness_row(cal, record)
    return _sorted_by_date(by_date)


def _sleep_score_fields(scores: dict) -> dict[str, Any]:
    return {
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


def _sleep_row(cal: date, record: dict) -> dict:
    deep = record.get("deepSleepSeconds") or 0
    light = record.get("lightSleepSeconds") or 0
    rem = record.get("remSleepSeconds") or 0
    return {
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
        **_sleep_score_fields(record.get("sleepScores") or {}),
    }


def _load_sleep(base: Path) -> list[dict]:
    by_date: dict[date, dict] = {}
    for record in _iter_json_records(base, f"{WELLNESS}/*_sleepData.json"):
        cal = _parse_date(record.get("calendarDate"))
        if cal is None:
            continue
        by_date[cal] = _sleep_row(cal, record)
    return _sorted_by_date(by_date)


def _hrv_snapshot_row(rec: dict) -> dict | None:
    """Health-snapshot HRV row (RMSSD/SDRR), or None when it has no HRV."""
    cal = _parse_date(rec.get("calendarDate"))
    summary = {s["summaryType"]: s for s in rec.get("summaryTypeDataList", [])}
    rmssd = summary.get("RMSSD_HRV", {}).get("avgValue")
    sdrr = summary.get("SDRR_HRV", {}).get("avgValue")
    if cal is None or (rmssd is None and sdrr is None):
        return None
    return {
        "calendar_date": cal,
        "source": "snapshot",
        "snapshot_time": rec.get("snapshotTimeOfDayType") or "",
        "rmssd": rmssd,
        "sdrr": sdrr,
        "hrv_status": None,
        "hrv_pct": None,
        "baseline_lo": None,
        "baseline_hi": None,
    }


def _hrv_daily_row(rec: dict) -> dict | None:
    """Daily health-status HRV row, or None when the HRV metric is empty."""
    cal = _parse_date(rec.get("calendarDate"))
    metrics = {m["type"]: m for m in rec.get("metrics", [])}
    hrv = metrics.get("HRV", {})
    if cal is None or not hrv.get("value"):
        return None
    return {
        "calendar_date": cal,
        "source": "daily",
        "snapshot_time": "",
        "rmssd": hrv.get("value"),
        "sdrr": None,
        "hrv_status": hrv.get("status"),
        "hrv_pct": hrv.get("percentage"),
        "baseline_lo": hrv.get("baselineLowerLimit"),
        "baseline_hi": hrv.get("baselineUpperLimit"),
    }


def _load_hrv(base: Path) -> list[dict]:
    # Health snapshots (RMSSD/SDRR, Apr 2024)
    snapshots = _iter_json_records(base, f"{WELLNESS}/*_wellnessActivities.json")
    rows = [r for r in map(_hrv_snapshot_row, snapshots) if r is not None]

    # Daily health status (Sep 2025+)
    daily = _iter_json_records(base, f"{WELLNESS}/*_healthStatusData.json")
    rows += [r for r in map(_hrv_daily_row, daily) if r is not None]

    rows.sort(key=lambda r: (r["calendar_date"], r["source"], r["snapshot_time"]))
    return rows


def _personal_record_row(pr: dict) -> dict:
    return {
        "personal_record_id": pr["personalRecordId"],
        "record_type": pr.get("personalRecordType"),
        "value": pr.get("value"),
        "pr_start_time_gmt": _parse_pr_date(pr.get("prStartTimeGMT")),
        "activity_id": pr.get("activityId"),
        "current": pr.get("current"),
    }


def _load_personal_records(base: Path) -> list[dict]:
    rows = []
    for chunk in _iter_json_records(base, f"{FITNESS}/*_personalRecord.json"):
        for pr in chunk.get("personalRecords", []):
            if pr.get("personalRecordId") is None:
                continue
            rows.append(_personal_record_row(pr))
    return rows


def _load_biometric_profile(base: Path) -> dict | None:
    files = _glob_sorted(base, f"{WELLNESS}/*_userBioMetricProfileData.json")
    if not files:
        return None
    data = _read_json(files[-1])
    profile = data[0] if isinstance(data, list) and data else data
    if not isinstance(profile, dict):
        return None
    return {
        "height_cm": profile.get("height"),
        "weight_kg": _scale(profile.get("weight"), 1_000),
        "vo2max": profile.get("vo2Max"),
        "lactate_threshold_hr": profile.get("lactateThresholdHeartRate"),
        "functional_threshold_power": profile.get("functionalThresholdPower"),
        "activity_class": profile.get("activityClass"),
    }
