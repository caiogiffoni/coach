"""
Transformers (Garmin Connect raw dict -> model kwargs) for the auto-pull.

These are intentionally defensive: Garmin's JSON shape varies by account,
firmware, and library version. Missing fields become None, which the models
accept.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .export_metrics import _vo2max_row
from .export_parsing import (
    _iso_to_dt,
    _ms_to_dt,
    _parse_date,
    _scale,
    _sorted_by_date,
    _sorted_by_date_sport,
    activity_effort_fields,
)
from .export_wellness import sleep_stage_fields


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dated_records(raw: list[dict]) -> list[tuple[date, dict]]:
    """Keep only dict records with a parseable ``calendarDate``."""
    pairs = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        cal = _parse_date(rec.get("calendarDate"))
        if cal is not None:
            pairs.append((cal, rec))
    return pairs


def _api_activity_row(a: dict) -> dict:
    """Live activity-search result → ``Activity`` kwargs.

    Unlike the export, the search uses seconds, metres, "YYYY-MM-DD hh:mm:ss"
    timestamps, ``averageHR``-style keys and a nested ``activityType``.
    """
    return {
        "activity_id": a["activityId"],
        "name": a.get("activityName"),
        "activity_type": _as_dict(a.get("activityType")).get("typeKey"),
        "sport_type": None,  # search only has a numeric sportTypeId
        "start_time_gmt": _iso_to_dt(a.get("startTimeGMT")),
        "start_time_local": _iso_to_dt(a.get("startTimeLocal")),
        "duration_min": _scale(a.get("duration"), 60),
        "distance_km": _scale(a.get("distance"), 1000),
        "elevation_gain_m": a.get("elevationGain"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "min_hr": a.get("minHR"),
        **activity_effort_fields(a),
    }


def _transform_activities(raw: list[dict]) -> list[dict]:
    return [
        _api_activity_row(a)
        for a in raw
        if isinstance(a, dict) and a.get("activityId") is not None
    ]


def _as_dict(value: Any) -> dict:
    """Return ``value`` if it is a non-empty dict, else ``{}``."""
    return value if isinstance(value, dict) and value else {}


def _total_stress(rec: dict) -> dict:
    # Some Garmin endpoints nest stress data; unwrap common shapes.
    stress = _as_dict(rec.get("allDayStress"))
    agg_list = stress.get("aggregatorList") or []
    return next(
        (a for a in agg_list if isinstance(a, dict) and a.get("type") == "TOTAL"),
        {},
    )


def _body_battery_stats(body_battery: dict) -> dict[str, Any]:
    return {
        s["bodyBatteryStatType"]: s["statsValue"]
        for s in body_battery.get("bodyBatteryStatList", [])
        if isinstance(s, dict) and "statsValue" in s
    }


def _wellness_activity_fields(rec: dict) -> dict[str, Any]:
    return {
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
    }


def _wellness_stress_fields(total: dict) -> dict[str, Any]:
    return {
        "avg_stress": _to_int(total.get("averageStressLevel")),
        "max_stress": _to_int(total.get("maxStressLevel")),
        "stress_duration_s": _to_int(total.get("stressDuration")),
        "rest_duration_s": _to_int(total.get("restDuration")),
    }


def _flat_stress(rec: dict) -> dict:
    """Stress totals from the flat ``usersummary/daily`` shape (live API)."""
    return {
        "averageStressLevel": rec.get("averageStressLevel"),
        "maxStressLevel": rec.get("maxStressLevel"),
        "stressDuration": rec.get("stressDuration"),
        "restDuration": rec.get("restStressDuration"),
    }


def _flat_body_battery_fields(rec: dict) -> dict[str, Any]:
    """Body battery from the flat ``usersummary/daily`` shape (live API)."""
    return {
        "bb_charged": _to_int(rec.get("bodyBatteryChargedValue")),
        "bb_drained": _to_int(rec.get("bodyBatteryDrainedValue")),
        "bb_highest": _to_int(rec.get("bodyBatteryHighestValue")),
        "bb_lowest": _to_int(rec.get("bodyBatteryLowestValue")),
        "bb_sleep_end": _to_int(rec.get("bodyBatteryAtWakeTime")),
        "bb_during_sleep": _to_int(rec.get("bodyBatteryDuringSleep")),
    }


def _body_battery_fields(rec: dict) -> dict[str, Any]:
    """Nested ``bodyBattery`` stat list when present, else the flat summary keys."""
    nested = _as_dict(rec.get("bodyBattery"))
    if nested.get("bodyBatteryStatList"):
        return _wellness_body_battery_fields(nested)
    return _flat_body_battery_fields(rec)


def _wellness_body_battery_fields(body_battery: dict) -> dict[str, Any]:
    stat_map = _body_battery_stats(body_battery)
    return {
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


def _transform_daily_wellness(raw: list[dict]) -> list[dict]:
    by_date: dict[date, dict] = {}
    for cal, rec in _dated_records(raw):
        by_date[cal] = {
            "calendar_date": cal,
            **_wellness_activity_fields(rec),
            **_wellness_stress_fields(_total_stress(rec) or _flat_stress(rec)),
            **_body_battery_fields(rec),
        }
    return _sorted_by_date(by_date)


def _sleep_scores(rec: dict) -> dict[str, Any]:
    """Live API nests the score as ``sleepScores.overall.value``."""
    overall = _as_dict(_as_dict(rec.get("sleepScores")).get("overall"))
    return {"overall_score": _to_int(overall.get("value"))}


def _transform_sleep(raw: list[dict]) -> list[dict]:
    """Live sleep summaries (epoch-ms timestamps) → ``Sleep`` kwargs."""
    by_date: dict[date, dict] = {}
    for cal, rec in _dated_records(raw):
        by_date[cal] = {
            "calendar_date": cal,
            "sleep_start_gmt": _ms_to_dt(rec.get("sleepStartTimestampGMT")),
            "sleep_end_gmt": _ms_to_dt(rec.get("sleepEndTimestampGMT")),
            **sleep_stage_fields(rec),
            "average_respiration": rec.get("averageRespirationValue"),
            **_sleep_scores(rec),
        }
    return _sorted_by_date(by_date)


def _vo2max_entries(rec: dict) -> list[dict]:
    """Each ``maxmet/daily`` record holds a ``generic`` and a ``cycling`` entry."""
    entries = [_as_dict(rec.get(key)) for key in ("generic", "cycling")]
    # Per-date reads (password client) put calendarDate on the outer record.
    return [
        {
            "calendarDate": rec.get("calendarDate"),
            **e,
            "vo2MaxValue": e.get("vo2MaxPreciseValue") or e.get("vo2MaxValue"),
        }
        for e in entries
        if e
    ]


def _transform_vo2max(raw: list[dict]) -> list[dict]:
    """Live ``maxmet/daily`` records → ``Vo2Max`` kwargs, one per (date, sport)."""
    rows = [
        _vo2max_row(entry, "metrics")
        for rec in raw
        if isinstance(rec, dict)
        for entry in _vo2max_entries(rec)
    ]
    by_key = {(r["calendar_date"], r["sport"]): r for r in rows if r["calendar_date"]}
    return _sorted_by_date_sport(by_key)


def _hrv_metric(summary: dict) -> dict:
    """The HRV metric entry, or the summary itself when it is flat."""
    metrics = {m["type"]: m for m in summary.get("metrics", []) if isinstance(m, dict)}
    hrv = metrics.get("HRV", {})
    if not hrv and summary.get("value"):
        return summary
    return hrv


def _hrv_status_row(cal: date, summary: dict) -> dict:
    """Row from the live ``/hrv-service`` summary: nightly avg + balanced band."""
    baseline = _as_dict(summary.get("baseline"))
    return {
        "calendar_date": cal,
        "source": "daily",
        "snapshot_time": "",
        "rmssd": summary["lastNightAvg"],
        "sdrr": None,
        "hrv_status": summary.get("status"),
        "hrv_pct": None,
        "baseline_lo": baseline.get("balancedLow"),
        "baseline_hi": baseline.get("balancedUpper"),
    }


def _hrv_row(cal: date, rec: dict) -> dict | None:
    # get_hrv_data may return a nested "hrvSummary" object.
    summary = rec.get("hrvSummary") or rec
    if not isinstance(summary, dict):
        return None
    if summary.get("lastNightAvg") is not None:
        return _hrv_status_row(cal, summary)
    return _hrv_metric_row(cal, summary)


def _hrv_metric_row(cal: date, summary: dict) -> dict | None:
    """Row from the export-style ``metrics[HRV]`` / flat ``rmssd`` shape."""
    hrv = _hrv_metric(summary)
    rmssd = hrv.get("value") or summary.get("rmssd")
    if rmssd is None:
        return None
    return {
        "calendar_date": cal,
        "source": "daily",
        "snapshot_time": "",
        "rmssd": rmssd,
        "sdrr": summary.get("sdrr"),
        "hrv_status": hrv.get("status") or summary.get("status"),
        "hrv_pct": hrv.get("percentage") or summary.get("percentage"),
        "baseline_lo": hrv.get("baselineLowerLimit")
        or summary.get("baselineLowerLimit"),
        "baseline_hi": hrv.get("baselineUpperLimit")
        or summary.get("baselineUpperLimit"),
    }


def _transform_hrv(raw: list[dict]) -> list[dict]:
    rows = (_hrv_row(cal, rec) for cal, rec in _dated_records(raw))
    return [row for row in rows if row is not None]


def _transform_training_readiness(raw: list[dict]) -> list[dict]:
    by_date: dict[date, dict] = {}
    for cal, rec in _dated_records(raw):
        by_date[cal] = {
            "calendar_date": cal,
            "score": _to_int(rec.get("score")),
            "level": rec.get("level"),
            "feedback_short": rec.get("feedbackShort"),
        }
    return _sorted_by_date(by_date)


def _transform_training_load(raw: list[dict]) -> list[dict]:
    by_date: dict[date, dict] = {}
    for cal, rec in _dated_records(raw):
        by_date[cal] = {
            "calendar_date": cal,
            "acute_load": _to_int(rec.get("dailyTrainingLoadAcute")),
            "chronic_load": _to_int(rec.get("dailyTrainingLoadChronic")),
            "acwr": rec.get("dailyAcuteChronicWorkloadRatio"),
            "acwr_status": rec.get("acwrStatus"),
        }
    return _sorted_by_date(by_date)
