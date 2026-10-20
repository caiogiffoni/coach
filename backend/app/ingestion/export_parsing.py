"""Shared parse and upsert helpers for Garmin export and API ingestion.

Unit conversions (see ``export_import`` for the full table) live here so the
GDPR export loaders and the Garmin Connect auto-pull produce identical rows.
"""

import json
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

FITNESS = "DI_CONNECT/DI-Connect-Fitness"
AGGREGATOR = "DI_CONNECT/DI-Connect-Aggregator"
METRICS = "DI_CONNECT/DI-Connect-Metrics"
WELLNESS = "DI_CONNECT/DI-Connect-Wellness"


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


def _iter_json_records(base: Path, pattern: str) -> Iterable[Any]:
    """Yield every top-level record from every file matching ``pattern``.

    Example:
        ``for rec in _iter_json_records(base, f"{METRICS}/X_*.json"): ...``
    """
    for f in _glob_sorted(base, pattern):
        yield from _read_json(f)


def _scale(value: float | int | None, divisor: float) -> float | None:
    """Divide ``value`` by ``divisor`` unless it is None (unit conversion)."""
    return value / divisor if value is not None else None


def _sorted_by_date(by_date: dict[date, dict]) -> list[dict]:
    """Return the rows of a date-keyed dedupe map in ascending date order."""
    return [by_date[d] for d in sorted(by_date)]


def _sorted_by_date_sport(by_key: dict[tuple, dict]) -> list[dict]:
    """Return rows keyed by ``(date, sport)`` sorted with None sports first."""
    return [by_key[k] for k in sorted(by_key, key=lambda k: (k[0], k[1] or ""))]


# ---------------------------------------------------------------------------
# Shared row builders
# ---------------------------------------------------------------------------


def activity_row(a: dict) -> dict:
    """Map a Garmin summarized-activity dict to ``Activity`` kwargs.

    Used by both the GDPR export loader and the Connect API pull, whose
    activity payloads share the same field names and units.

    Example:
        ``activity_row({"activityId": 1, "distance": 500_000})["distance_km"]``
        returns ``5.0``.
    """
    return {
        "activity_id": a["activityId"],
        "name": a.get("name"),
        "activity_type": a.get("activityType"),
        "sport_type": a.get("sportType"),
        "start_time_gmt": _ms_to_dt(a.get("startTimeGmt")),
        "start_time_local": _ms_to_dt(a.get("startTimeLocal")),
        "duration_min": _scale(a.get("duration"), 60_000),
        "distance_km": _scale(a.get("distance"), 100_000),
        "elevation_gain_m": _scale(a.get("elevationGain"), 100),
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
    }


# ---------------------------------------------------------------------------
# Upsert helper
# ---------------------------------------------------------------------------


def _existing_by_key(
    db: Session, model: type[Any], key_fields: tuple[str, ...]
) -> dict[tuple[Any, ...], Any]:
    existing: dict[tuple[Any, ...], Any] = {}
    for raw_obj in db.scalars(select(model)):
        obj: Any = raw_obj
        existing[tuple(getattr(obj, k) for k in key_fields)] = obj
    return existing


def _upsert_many(
    db: Session,
    model: type[Any],
    key_fields: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
) -> int:
    """Insert or update rows keyed by key_fields. Returns rows processed."""
    rows = list(rows)
    if not rows:
        return 0
    existing = _existing_by_key(db, model, key_fields)
    for row in rows:
        key = tuple(row.get(k) for k in key_fields)
        obj = existing.get(key)
        if obj is None:
            existing[key] = model(**row)
            db.add(existing[key])
            continue
        for field, value in row.items():
            setattr(obj, field, value)
    return len(rows)
