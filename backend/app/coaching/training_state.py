"""
Training state — port of temp/utils.py::_current_state (see constraints.py).

Reads the imported Garmin data from the SQLAlchemy store and condenses it
into a TrainingState snapshot. Every recency window anchors to the latest
date in the data (same convention as profile/seed.py), never to wall-clock.
"""

from datetime import date, timedelta
from statistics import median
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ingestion.models import (
    Activity,
    DailyWellness,
    Hrv,
    Sleep,
    TrainingHistory,
    TrainingLoad,
    TrainingReadiness,
)
from ..profile.models import Profile
from ..profile.seed import RUN_TYPES
from .constraint_schemas import TrainingState, WeeklyVolume

VOLUME_WINDOW_WEEKS = 8  # recent-volume window, same as seed.py
RHR_BASELINE_DAYS = 30
SLEEP_LOOKBACK_NIGHTS = 7

# --- Hard-session classification (ported plan_week avg-HR/TE approach) -------
HARD_AEROBIC_TE = 3.5
HARD_ANAEROBIC_TE = 1.5
HARD_HR_LTHR_FRACTION = 0.90  # avg HR ≥90% of LTHR ≈ Z3+ in zones.py terms
HARD_LOOKBACK_DAYS = 60

_DatedRow = TypeVar("_DatedRow", TrainingLoad, TrainingReadiness, TrainingHistory)
StatusValue = str | int | float | None


def iso_monday(d: date) -> date:
    """Monday of the ISO week containing ``d``.

    Example:
        >>> iso_monday(date(2026, 6, 4))
        datetime.date(2026, 6, 1)
    """
    return d - timedelta(days=d.weekday())


def _latest_run_date(db: Session) -> date | None:
    latest_run = db.scalar(
        select(func.max(Activity.start_time_local)).where(
            Activity.activity_type.in_(RUN_TYPES)
        )
    )
    return latest_run.date() if latest_run is not None else None


def _latest_data_date(db: Session) -> date | None:
    """Most recent date across every table the engine reads."""
    candidates: list[date] = []
    latest_run = _latest_run_date(db)
    if latest_run is not None:
        candidates.append(latest_run)
    for model in (DailyWellness, Sleep, Hrv, TrainingLoad, TrainingReadiness):
        latest = db.scalar(select(func.max(model.calendar_date)))
        if latest is not None:
            candidates.append(latest)
    return max(candidates) if candidates else None


def _run_km_by_monday(db: Session, first_monday: date) -> dict[date, float]:
    runs = db.scalars(
        select(Activity).where(
            Activity.activity_type.in_(RUN_TYPES),
            Activity.start_time_local >= first_monday,
            Activity.distance_km > 0,
        )
    )
    by_monday: dict[date, float] = {}
    for run in runs:
        start = run.start_time_local
        distance = run.distance_km
        assert start is not None and distance is not None
        monday = iso_monday(start.date())
        by_monday[monday] = by_monday.get(monday, 0.0) + distance
    return by_monday


def _weekly_volumes(
    db: Session, anchor: date, weeks: int = VOLUME_WINDOW_WEEKS
) -> list[WeeklyVolume]:
    """Running km per ISO week for the `weeks` weeks ending at `anchor`."""
    first_monday = iso_monday(anchor) - timedelta(weeks=weeks - 1)
    by_monday = _run_km_by_monday(db, first_monday)
    mondays = [first_monday + timedelta(weeks=i) for i in range(weeks)]
    return [
        WeeklyVolume(
            week_start=monday,
            volume_km=round(by_monday.get(monday, 0.0), 2),
            # A week is complete once its Sunday is within data coverage.
            complete=(monday + timedelta(days=6)) <= anchor,
        )
        for monday in mondays
    ]


def _avg_run_week_km(volumes: list[WeeklyVolume]) -> float:
    """Average over weeks that had any running (empty weeks are ignored)."""
    run_weeks = [v.volume_km for v in volumes if v.volume_km > 0]
    return round(sum(run_weeks) / len(run_weeks), 2) if run_weeks else 0.0


def _last_complete_week_km(volumes: list[WeeklyVolume]) -> float | None:
    complete = [v for v in volumes if v.complete]
    return complete[-1].volume_km if complete else None


def _is_hard_run(run: Activity, threshold_hr: int | None) -> bool:
    """plan_week-style classification: training effect first, avg HR vs LTHR."""
    if run.aerobic_training_effect and run.aerobic_training_effect >= HARD_AEROBIC_TE:
        return True
    if (
        run.anaerobic_training_effect
        and run.anaerobic_training_effect >= HARD_ANAEROBIC_TE
    ):
        return True
    if (
        run.avg_hr
        and threshold_hr
        and run.avg_hr >= HARD_HR_LTHR_FRACTION * threshold_hr
    ):
        return True
    return False


def _hard_run_dates(db: Session, since: date, threshold_hr: int | None) -> list[date]:
    recent = db.scalars(
        select(Activity).where(
            Activity.activity_type.in_(RUN_TYPES),
            Activity.start_time_local >= since,
        )
    )
    return [
        r.start_time_local.date()
        for r in recent
        if r.start_time_local is not None and _is_hard_run(r, threshold_hr)
    ]


def _days_since_last_hard(
    db: Session, profile: Profile, as_of: date | None, last_run_date: date | None
) -> int | None:
    if not (as_of and last_run_date):
        return None
    cutoff = last_run_date - timedelta(days=HARD_LOOKBACK_DAYS)
    hard_dates = _hard_run_dates(db, cutoff, profile.threshold_hr)
    return (as_of - max(hard_dates)).days if hard_dates else None


def _latest_row(db: Session, model: type[_DatedRow]) -> _DatedRow | None:
    return db.scalars(select(model).order_by(model.calendar_date.desc())).first()


def _latest_running_history(db: Session) -> TrainingHistory | None:
    """Prefer the RUNNING-sport status; fall back to any sport's latest row."""
    running = db.scalars(
        select(TrainingHistory)
        .where(TrainingHistory.sport == "RUNNING")
        .order_by(TrainingHistory.calendar_date.desc())
    ).first()
    return running or _latest_row(db, TrainingHistory)


def _latest_daily_hrv(db: Session) -> Hrv | None:
    return db.scalars(
        select(Hrv).where(Hrv.source == "daily").order_by(Hrv.calendar_date.desc())
    ).first()


def _garmin_status_fields(db: Session) -> dict[str, StatusValue]:
    """Latest Garmin-computed load / readiness / status / HRV values."""
    load = _latest_row(db, TrainingLoad)
    readiness = _latest_row(db, TrainingReadiness)
    history = _latest_running_history(db)
    hrv = _latest_daily_hrv(db)
    return {
        "training_status": history.training_status if history else None,
        "acwr": load.acwr if load else None,
        "acwr_status": load.acwr_status if load else None,
        "acute_load": load.acute_load if load else None,
        "chronic_load": load.chronic_load if load else None,
        "readiness_score": readiness.score if readiness else None,
        "readiness_level": readiness.level if readiness else None,
        "hrv_rmssd": hrv.rmssd if hrv else None,
        "hrv_status": hrv.hrv_status if hrv else None,
        "hrv_baseline_lo": hrv.baseline_lo if hrv else None,
        "hrv_baseline_hi": hrv.baseline_hi if hrv else None,
    }


def _resting_hr_stats(
    db: Session, as_of: date | None
) -> tuple[int | None, float | None]:
    """(latest RHR, 30-day median RHR rounded to 0.1) up to ``as_of``."""
    if not as_of:
        return None, None
    rows = db.scalars(
        select(DailyWellness.resting_hr)
        .where(
            DailyWellness.calendar_date <= as_of,
            DailyWellness.calendar_date >= as_of - timedelta(days=RHR_BASELINE_DAYS),
            DailyWellness.resting_hr.is_not(None),
        )
        .order_by(DailyWellness.calendar_date)
    ).all()
    values = [v for v in rows if v is not None]
    if not values:
        return None, None
    return values[-1], round(median(values), 1)


def _sleep_averages(db: Session) -> tuple[float | None, float | None]:
    """(avg hours, avg score) over the last SLEEP_LOOKBACK_NIGHTS nights."""
    nights = db.scalars(
        select(Sleep).order_by(Sleep.calendar_date.desc()).limit(SLEEP_LOOKBACK_NIGHTS)
    ).all()
    totals = [n.total_sleep_s for n in nights if n.total_sleep_s]
    scores = [n.overall_score for n in nights if n.overall_score is not None]
    hours = round(sum(totals) / len(totals) / 3600, 1) if totals else None
    score = round(sum(scores) / len(scores), 1) if scores else None
    return hours, score


def compute_training_state(db: Session, profile: Profile) -> TrainingState:
    """Snapshot every metric the constraint engine decides on.

    Volumes anchor to the latest run; all other signals anchor to the latest
    date present in any imported table.

    Example:
        >>> state = compute_training_state(db, profile)
        >>> state.avg_weekly_km
        31.5
    """
    as_of = _latest_data_date(db)
    last_run_date = _latest_run_date(db)
    volumes = _weekly_volumes(db, last_run_date) if last_run_date else []
    resting_hr_latest, resting_hr_baseline = _resting_hr_stats(db, as_of)
    sleep_hours, sleep_score = _sleep_averages(db)
    return TrainingState(
        as_of=as_of,
        weekly_volumes=volumes,
        avg_weekly_km=_avg_run_week_km(volumes),
        last_complete_week_km=_last_complete_week_km(volumes),
        days_since_last_run=(
            (as_of - last_run_date).days if (as_of and last_run_date) else None
        ),
        days_since_last_hard=_days_since_last_hard(db, profile, as_of, last_run_date),
        resting_hr_latest=resting_hr_latest,
        resting_hr_baseline=resting_hr_baseline,
        sleep_avg_hours_7d=sleep_hours,
        sleep_avg_score_7d=sleep_score,
        **_garmin_status_fields(db),
    )
