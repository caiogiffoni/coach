"""
Seed an athlete profile from imported Garmin data.

Semantics: seeding creates the profile if it doesn't exist yet, then fills
only fields that are currently unset (None, or empty list for JSON fields).
Any value the user has set manually — before or after a previous seed — is
never overwritten. Goal fields and injury history are always manual
(PLAN.md locked decision #11) and are never touched. ``seeded_at`` is
stamped on every run.

All recency windows are measured back from the latest date present in the
imported data, not from wall-clock today, so a stale export still seeds
from its own most recent data.
"""

from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ingestion.models import Activity, BiometricProfile, DailyWellness, PersonalRecord
from .models import Profile

RUN_TYPES = ("running", "treadmill_running")

# PersonalRecord.record_type → race distance in km.
RACE_DISTANCES_KM = {
    "Best 1km Run": 1.0,
    "Best 1 Mile Run": 1.609,
    "Best 5km Run": 5.0,
    "Best 10km Run": 10.0,
    "Best Half Marathon": 21.0975,
    "Best Full Marathon": 42.195,
}

# avg-HR buckets (bpm) used to classify recent runs, ported from
# temp/utils.py::_compute_pace_zones (tuned for this athlete, LTHR 185).
_THRESHOLD_HR_RANGE = (165, 176)
_MODERATE_HR_RANGE = (155, 165)


def _latest_run_date(db: Session) -> datetime | None:
    return db.scalar(
        select(func.max(Activity.start_time_local)).where(
            Activity.activity_type.in_(RUN_TYPES)
        )
    )


def _recent_runs(db: Session, days: int) -> list[Activity]:
    """Runs from the last `days` days of data with usable pace/HR."""
    latest = _latest_run_date(db)
    if latest is None:
        return []
    cutoff = latest - timedelta(days=days)
    return list(
        db.scalars(
            select(Activity).where(
                Activity.activity_type.in_(RUN_TYPES),
                Activity.start_time_local >= cutoff,
                Activity.distance_km > 0,
                Activity.duration_min > 0,
            )
        )
    )


def _seed_max_hr(db: Session) -> int | None:
    """Highest HR observed in activities or daily wellness."""
    observed = [
        v
        for v in (
            db.scalar(select(func.max(Activity.max_hr))),
            db.scalar(select(func.max(DailyWellness.max_hr))),
        )
        if v is not None
    ]
    return int(max(observed)) if observed else None


def _seed_resting_hr(db: Session) -> int | None:
    """Median daily resting HR over the last 30 days of wellness data."""
    latest = db.scalar(select(func.max(DailyWellness.calendar_date)))
    if latest is None:
        return None
    values = [
        v
        for v in db.scalars(
            select(DailyWellness.resting_hr).where(
                DailyWellness.calendar_date >= latest - timedelta(days=30),
                DailyWellness.resting_hr.is_not(None),
            )
        )
        if v is not None
    ]
    return int(round(median(values))) if values else None


def _seed_weekly_volume_km(db: Session) -> float | None:
    """Mean weekly running km over the last 8 weeks of activity data."""
    runs = _recent_runs(db, days=8 * 7)
    if not runs:
        return None
    weekly: dict[tuple[int, int], float] = {}
    for run in runs:
        start = run.start_time_local
        distance = run.distance_km
        assert start is not None and distance is not None
        year, week, _ = start.isocalendar()
        weekly[(year, week)] = weekly.get((year, week), 0.0) + distance
    return round(sum(weekly.values()) / len(weekly), 2)


def _seed_recent_race(db: Session) -> tuple[float, int] | None:
    """Most recent currently-standing run PR as (distance_km, time_sec)."""
    prs = db.scalars(
        select(PersonalRecord).where(
            PersonalRecord.current.is_(True),
            PersonalRecord.pr_start_time_gmt.is_not(None),
        )
    )
    races = [p for p in prs if p.record_type in RACE_DISTANCES_KM and p.value]
    if not races:
        return None
    latest = max(races, key=lambda p: p.pr_start_time_gmt or datetime.min)
    assert latest.record_type is not None
    assert latest.value is not None
    return RACE_DISTANCES_KM[latest.record_type], int(latest.value)


def _seed_threshold_pace(db: Session) -> int | None:
    """
    Threshold pace (sec/km) from the last 120 days of runs classified by
    avg HR — port of temp/utils.py::_compute_pace_zones. Uses the mean pace
    of the threshold-HR bucket, falling back to the moderate bucket.
    """
    runs = [r for r in _recent_runs(db, days=120) if r.avg_hr is not None]

    def mean_pace(hr_lo: int, hr_hi: int) -> float | None:
        paces: list[float] = []
        for r in runs:
            avg_hr = r.avg_hr
            distance = r.distance_km
            if avg_hr is None or distance is None:
                continue
            duration = r.duration_min
            assert duration is not None
            if hr_lo <= avg_hr < hr_hi:
                paces.append(duration * 60 / distance)
        return sum(paces) / len(paces) if paces else None

    pace = mean_pace(*_THRESHOLD_HR_RANGE) or mean_pace(*_MODERATE_HR_RANGE)
    return round(pace) if pace else None


def _seed_preferred_days(db: Session) -> list[int]:
    """
    Most common run weekdays (0=Mon..6=Sun) over the last 120 days.
    A weekday counts as preferred if it has at least half as many runs as
    the most frequent weekday.
    """
    counts: dict[int, int] = {}
    for run in _recent_runs(db, days=120):
        start = run.start_time_local
        assert start is not None
        day = start.weekday()
        counts[day] = counts.get(day, 0) + 1
    if not counts:
        return []
    threshold = max(counts.values()) / 2
    return sorted(day for day, n in counts.items() if n >= threshold)


def has_imported_data(db: Session) -> bool:
    return bool(
        db.scalar(select(func.count()).select_from(Activity))
        or db.scalar(select(func.count()).select_from(DailyWellness))
    )


def seed_profile_from_data(user_id: int, db: Session) -> Profile:
    """Fill unset profile fields from imported data (see module docstring)."""
    profile = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)

    if profile.threshold_hr is None:
        bio = db.scalar(select(BiometricProfile).limit(1))
        if bio and bio.lactate_threshold_hr:
            profile.threshold_hr = int(bio.lactate_threshold_hr)

    if profile.max_hr is None:
        profile.max_hr = _seed_max_hr(db)

    if profile.resting_hr is None:
        profile.resting_hr = _seed_resting_hr(db)

    if profile.current_weekly_volume_km is None:
        profile.current_weekly_volume_km = _seed_weekly_volume_km(db)

    if profile.recent_race_distance_km is None or profile.recent_race_time_sec is None:
        race = _seed_recent_race(db)
        if race:
            profile.recent_race_distance_km, profile.recent_race_time_sec = race

    if profile.threshold_pace_sec_per_km is None:
        profile.threshold_pace_sec_per_km = _seed_threshold_pace(db)

    if not profile.preferred_days:
        profile.preferred_days = _seed_preferred_days(db)

    profile.seeded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    return profile
