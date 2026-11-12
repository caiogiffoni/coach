"""Daily acute/chronic training load rebuilt from per-activity load.

The Garmin Connect Personal API exposes ``activityTrainingLoad`` on every
activity but not Garmin's daily training-status series (that endpoint 404s),
so the series is rebuilt here with the rolling-average ACWR model:

- acute load   = sum of the last 7 days (today included)
- chronic load = sum of the last 28 days / 4 (an average week)

Garmin's watch weights days exponentially, so values differ slightly from the
device, but the ratio bands below match the ones Garmin Connect shows.
Rows come out in Garmin's raw training-status shape so
``api_transform._transform_training_load`` handles them like any other source.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

ACUTE_DAYS = 7
CHRONIC_DAYS = 28
# Callers must fetch activities this many days before ``start_date``.
CHRONIC_LOOKBACK_DAYS = CHRONIC_DAYS - 1

# (exclusive upper bound, status) — Garmin Connect's acute load ratio bands.
_ACWR_BANDS: tuple[tuple[float, str], ...] = (
    (0.8, "LOW"),
    (1.5, "OPTIMAL"),
    (2.0, "HIGH"),
)


def acwr_status(acwr: float | None) -> str | None:
    """Garmin-style band for an acute:chronic ratio.

    Example:
        ``acwr_status(1.2)  # "OPTIMAL"``
    """
    if acwr is None:
        return None
    return next((name for limit, name in _ACWR_BANDS if acwr < limit), "VERY_HIGH")


def _activity_day(activity: dict) -> date | None:
    """Local calendar day of an activity (``startTimeLocal`` "YYYY-MM-DD hh:mm:ss")."""
    start = activity.get("startTimeLocal")
    if not isinstance(start, str):
        return None
    try:
        return date.fromisoformat(start[:10])
    except ValueError:
        return None


def _load_by_day(activities: list[dict]) -> dict[date, float]:
    """Sum ``activityTrainingLoad`` per local day; skip activities without one."""
    totals: dict[date, float] = defaultdict(float)
    for activity in activities:
        day = _activity_day(activity)
        load = activity.get("activityTrainingLoad")
        if day is not None and isinstance(load, (int, float)):
            totals[day] += float(load)
    return totals


def _window_sum(totals: dict[date, float], day: date, days: int) -> float:
    return sum(totals.get(day - timedelta(days=i), 0.0) for i in range(days))


def _load_row(totals: dict[date, float], day: date) -> dict:
    acute = round(_window_sum(totals, day, ACUTE_DAYS), 1)
    chronic = round(_window_sum(totals, day, CHRONIC_DAYS) / 4, 1)
    ratio = round(acute / chronic, 2) if chronic else None
    return {
        "calendarDate": day.isoformat(),
        "dailyTrainingLoadAcute": acute,
        "dailyTrainingLoadChronic": chronic,
        "dailyAcuteChronicWorkloadRatio": ratio,
        "acwrStatus": acwr_status(ratio),
    }


def training_load_from_activities(
    activities: list[dict], start_date: date, end_date: date
) -> list[dict]:
    """One raw training-load row per day from ``start_date`` to ``end_date``.

    ``activities`` must reach back ``CHRONIC_LOOKBACK_DAYS`` before
    ``start_date`` for the first rows' chronic load to be complete.

    Example:
        ``training_load_from_activities(acts, date(2026, 11, 1), date(2026, 11, 7))``
    """
    totals = _load_by_day(activities)
    days = (end_date - start_date).days + 1
    return [_load_row(totals, start_date + timedelta(days=i)) for i in range(days)]
