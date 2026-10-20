"""
Transformers (Garmin Connect raw dict -> model kwargs) for the auto-pull.

These are intentionally defensive: Garmin's JSON shape varies by account,
firmware, and library version. Missing fields become None, which the models
accept.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .export_parsing import _parse_date, _sorted_by_date, activity_row


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


def _transform_activities(raw: list[dict]) -> list[dict]:
    return [
        activity_row(a)
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
            **_wellness_stress_fields(_total_stress(rec)),
            **_wellness_body_battery_fields(_as_dict(rec.get("bodyBattery"))),
        }
    return _sorted_by_date(by_date)


def _hrv_metric(summary: dict) -> dict:
    """The HRV metric entry, or the summary itself when it is flat."""
    metrics = {m["type"]: m for m in summary.get("metrics", []) if isinstance(m, dict)}
    hrv = metrics.get("HRV", {})
    if not hrv and summary.get("value"):
        return summary
    return hrv


def _hrv_row(cal: date, rec: dict) -> dict | None:
    # get_hrv_data may return a nested "hrvSummary" object.
    summary = rec.get("hrvSummary") or rec
    if not isinstance(summary, dict):
        return None
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
