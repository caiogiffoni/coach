"""GDPR export loaders for DI-Connect-Metrics datasets.

VO2max, race predictions, training load, readiness and training history.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

from .export_parsing import (
    METRICS,
    _iter_json_records,
    _parse_date,
    _sorted_by_date,
    _sorted_by_date_sport,
)


def _vo2max_row(rec: dict, source: str) -> dict:
    """VO2max row; ``max_met`` only exists in metrics, activity id only in activity."""
    is_activity = source == "activity"
    return {
        "calendar_date": _parse_date(rec.get("calendarDate")),
        "sport": rec.get("sport"),
        "vo2max_value": rec.get("vo2MaxValue"),
        "max_met": None if is_activity else rec.get("maxMet"),
        "activity_id": rec.get("activityId") if is_activity else None,
        "source": source,
    }


def _load_vo2max(base: Path) -> list[dict]:
    activity = _iter_json_records(base, f"{METRICS}/ActivityVo2Max_*.json")
    rows = [_vo2max_row(rec, "activity") for rec in activity]
    metrics = _iter_json_records(base, f"{METRICS}/MetricsMaxMetData_*.json")
    rows += [_vo2max_row(rec, "metrics") for rec in metrics]
    # Dedupe per (date, sport), preferring the "metrics" source on ties
    rows = [r for r in rows if r["calendar_date"] is not None]
    rows.sort(key=lambda r: (r["calendar_date"], r["source"]))
    by_key: dict[tuple, dict] = {}
    for r in rows:
        by_key[(r["calendar_date"], r["sport"])] = r
    return _sorted_by_date_sport(by_key)


def _race_prediction_row(cal: date, rec: dict) -> dict:
    return {
        "calendar_date": cal,
        "race_time_5k_s": rec.get("raceTime5K"),
        "race_time_10k_s": rec.get("raceTime10K"),
        "race_time_half_s": rec.get("raceTimeHalf"),
        "race_time_marathon_s": rec.get("raceTimeMarathon"),
    }


def _training_load_row(cal: date, rec: dict) -> dict:
    return {
        "calendar_date": cal,
        "acute_load": rec.get("dailyTrainingLoadAcute"),
        "chronic_load": rec.get("dailyTrainingLoadChronic"),
        "acwr": rec.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_status": rec.get("acwrStatus"),
    }


def _training_readiness_row(cal: date, rec: dict) -> dict:
    return {
        "calendar_date": cal,
        "score": rec.get("score"),
        "level": rec.get("level"),
        "feedback_short": rec.get("feedbackShort"),
    }


def _load_by_date(
    base: Path, pattern: str, build_row: Callable[[date, dict], dict]
) -> list[dict]:
    """Load ``pattern`` files into one row per date (last record wins)."""
    by_date: dict[date, dict] = {}
    for rec in _iter_json_records(base, f"{METRICS}/{pattern}"):
        # calendarDate arrives as epoch ms in some files (e.g. training load)
        cal = _parse_date(rec.get("calendarDate"))
        if cal is None:
            continue
        by_date[cal] = build_row(cal, rec)
    return _sorted_by_date(by_date)


def _load_race_predictions(base: Path) -> list[dict]:
    return _load_by_date(base, "RunRacePredictions_*.json", _race_prediction_row)


def _load_training_load(base: Path) -> list[dict]:
    return _load_by_date(base, "MetricsAcuteTrainingLoad_*.json", _training_load_row)


def _load_training_readiness(base: Path) -> list[dict]:
    return _load_by_date(base, "TrainingReadinessDTO_*.json", _training_readiness_row)


def _training_history_row(cal: date, rec: dict) -> dict:
    return {
        "calendar_date": cal,
        "sport": rec.get("sport"),
        "training_status": rec.get("trainingStatus"),
        "fitness_level_trend": rec.get("fitnessLevelTrend"),
        "feedback_phrase": rec.get("trainingStatus2FeedbackPhrase"),
    }


def _load_training_history(base: Path) -> list[dict]:
    by_key: dict[tuple, dict] = {}
    for rec in _iter_json_records(base, f"{METRICS}/TrainingHistory_*.json"):
        cal = _parse_date(rec.get("calendarDate"))
        if cal is None:
            continue
        by_key[(cal, rec.get("sport"))] = _training_history_row(cal, rec)
    return _sorted_by_date_sport(by_key)
