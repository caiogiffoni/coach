"""
FIT file parser for Garmin .FIT activity uploads.

Maps the FIT session record onto the Activity model columns, using the same
unit conventions as export_import.py:

  duration   seconds → minutes (÷ 60)
  distance   meters  → km      (÷ 1_000)
  elevation  meters  → meters  (no change)
  calories   kcal    → kcal    (no change)
  timestamps FIT UTC → naive UTC datetime

The natural key is ``activity_id``, derived from the session start time as
``int(start_time.timestamp())`` so re-uploading the same activity is idempotent.
"""

import io
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fitparse import FitFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity

FitParser = Callable[[Path], dict]


def _normalize_sport(name: str | None) -> str | None:
    """Return a lower-case sport name ('running', 'cycling', etc.) or None."""
    if not name:
        return None
    name = str(name).strip().lower()
    if name in {"", "generic", "none"}:
        return None
    return name


def _get_field(record: Any, *names: str) -> Any:
    """Return the first present FIT field value, or None."""
    for name in names:
        value = record.get_value(name)
        if value is not None:
            return value
    return None


def _ms_to_dt(ts: datetime | int | float | None) -> datetime | None:
    """Accept a FIT datetime or epoch-ms int and return naive UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)


def _parse_session(session: Any) -> dict:
    """Turn a fitparse session record into an Activity kwargs dict."""
    sport = _normalize_sport(_get_field(session, "sport"))
    sub_sport = _normalize_sport(_get_field(session, "sub_sport"))
    start_raw = _get_field(session, "start_time")
    start_time = _ms_to_dt(start_raw)

    duration_s = _get_field(session, "total_elapsed_time", "total_timer_time")
    distance_m = _get_field(session, "total_distance")
    elevation_m = _get_field(session, "total_ascent")
    avg_hr = _get_field(session, "avg_heart_rate")
    max_hr = _get_field(session, "max_heart_rate")
    min_hr = _get_field(session, "min_heart_rate")
    calories = _get_field(session, "total_calories")

    # Stable numeric ID from the session start time (UTC epoch seconds).
    if isinstance(start_raw, datetime):
        activity_id = int(start_raw.timestamp())
    elif isinstance(start_raw, (int, float)):
        activity_id = int(start_raw / 1000)
    else:
        activity_id = None

    return {
        "activity_id": activity_id,
        "name": _get_field(session, "name"),
        "activity_type": sub_sport or sport,
        "sport_type": sport,
        "start_time_gmt": start_time,
        "start_time_local": start_time,
        "duration_min": duration_s / 60 if duration_s is not None else None,
        "distance_km": distance_m / 1_000 if distance_m is not None else None,
        "elevation_gain_m": elevation_m,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "min_hr": min_hr,
        "calories": calories,
        "vo2max_value": None,
        "aerobic_training_effect": _get_field(session, "total_training_effect"),
        "anaerobic_training_effect": _get_field(
            session, "total_anaerobic_training_effect"
        ),
        "training_load": _get_field(session, "training_stress_score"),
        "lap_count": _get_field(session, "num_laps"),
        "is_pr": None,
    }


def parse_fit_file(path_or_bytes: Path | bytes) -> dict:
    """Parse a FIT file and return an Activity kwargs dict.

    Raises ValueError when the file is not a valid FIT file, no session record
    is found, or the start time is missing.
    """
    try:
        if isinstance(path_or_bytes, bytes):
            fit = FitFile(io.BytesIO(path_or_bytes))
        else:
            fit = FitFile(str(path_or_bytes))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid FIT file: {exc}") from exc

    session = None
    try:
        for record in fit.get_messages("session"):
            session = record
            break
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid FIT file: {exc}") from exc

    if session is None:
        raise ValueError("FIT file has no session record")

    parsed = _parse_session(session)
    if parsed["activity_id"] is None:
        raise ValueError("FIT session has no start_time")
    return parsed


def upsert_activity_from_fit(db: Session, parsed: dict) -> Activity:
    """Insert or update an Activity row from a parsed FIT session dict."""
    activity_id = parsed["activity_id"]
    existing = db.scalar(select(Activity).where(Activity.activity_id == activity_id))
    if existing is None:
        existing = Activity(**parsed)
        db.add(existing)
    else:
        for field, value in parsed.items():
            setattr(existing, field, value)
    return existing


def fit_parser_dependency() -> FitParser:
    """FastAPI dependency returning the real FIT parser."""
    return parse_fit_file
