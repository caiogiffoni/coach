"""
Auto-pull recent data from Garmin Connect into the normalized SQLite store.

Uses the dependency-injected ``GarminClient`` protocol so tests can substitute
a fake client. Each dataset is pulled for a configurable look-back window,
transformed (``api_transform.py``) into the same kwargs used by
``export_import.py``, and upserted on
its natural key. If a particular Garmin endpoint is unavailable in the
installed ``python-garminconnect`` version, the sync records that in
``SyncReport.skipped_datasets`` instead of crashing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..garmin.client import GarminClient
from .api_transform import (
    _transform_activities,
    _transform_daily_wellness,
    _transform_hrv,
    _transform_training_load,
    _transform_training_readiness,
)
from .export_parsing import _upsert_many
from .models import (
    Activity,
    DailyWellness,
    Hrv,
    TrainingLoad,
    TrainingReadiness,
)

logger = logging.getLogger(__name__)

DEFAULT_DAYS_BACK = 14


class SyncReport(BaseModel):
    """Result of a Garmin Connect auto-pull."""

    activities: int = 0
    daily_wellness: int = 0
    hrv: int = 0
    training_readiness: int = 0
    training_load: int = 0
    skipped_datasets: list[str] = []
    newest_date: date | None = None
    needs_mfa: bool = False


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def latest_local_date(db: Session) -> date | None:
    """Most recent date present across the synced ingestion tables."""
    candidates: list[date] = []
    for model, column in (
        (DailyWellness, DailyWellness.calendar_date),
        (Hrv, Hrv.calendar_date),
        (TrainingLoad, TrainingLoad.calendar_date),
        (TrainingReadiness, TrainingReadiness.calendar_date),
    ):
        latest = db.scalar(select(func.max(column)))
        if latest is not None:
            candidates.append(latest)

    latest_run = db.scalar(select(func.max(Activity.start_time_local)))
    if latest_run is not None:
        candidates.append(latest_run.date())

    return max(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SyncDataset:
    """One best-effort dataset pulled from Garmin and upserted locally."""

    name: str  # SyncReport field and skipped_datasets label
    fetch_method: str  # GarminClient method taking (start_date, end_date)
    model: type[Any]
    key_fields: tuple[str, ...]
    transform: Callable[[list[dict]], list[dict]]


_SYNC_DATASETS: tuple[_SyncDataset, ...] = (
    _SyncDataset(
        "activities",
        "get_activities",
        Activity,
        ("activity_id",),
        _transform_activities,
    ),
    _SyncDataset(
        "daily_wellness",
        "get_daily_wellness",
        DailyWellness,
        ("calendar_date",),
        _transform_daily_wellness,
    ),
    _SyncDataset(
        "hrv",
        "get_hrv",
        Hrv,
        ("calendar_date", "source", "snapshot_time"),
        _transform_hrv,
    ),
    _SyncDataset(
        "training_readiness",
        "get_training_readiness",
        TrainingReadiness,
        ("calendar_date",),
        _transform_training_readiness,
    ),
    _SyncDataset(
        "training_load",
        "get_training_load",
        TrainingLoad,
        ("calendar_date",),
        _transform_training_load,
    ),
)


def _log_sync_failure(
    dataset_name: str, start_date: date, end_date: date, exc: Exception
) -> None:
    """Structured warning for a skipped dataset (no credentials logged)."""
    logger.warning(
        "Sync %s failed: %s",
        dataset_name,
        exc,
        extra={
            "dataset": dataset_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "error": repr(exc),
        },
    )


def _sync_dataset(
    db: Session,
    client: GarminClient,
    dataset: _SyncDataset,
    start_date: date,
    end_date: date,
) -> int | None:
    """Pull and upsert one dataset; return row count or None when it failed."""
    try:
        raw = getattr(client, dataset.fetch_method)(start_date, end_date)
        return _upsert_many(
            db, dataset.model, dataset.key_fields, dataset.transform(raw)
        )
    except Exception as exc:  # noqa: BLE001 — best-effort dataset
        _log_sync_failure(dataset.name, start_date, end_date, exc)
        return None


def sync_garmin_data(
    db: Session,
    client: GarminClient,
    days_back: int = DEFAULT_DAYS_BACK,
    as_of: date | None = None,
) -> SyncReport:
    """Pull the last ``days_back`` days from Garmin and upsert locally.

    ``as_of`` defaults to the latest date already present in the local data, or
    ``date.today()`` if the database is empty. This keeps re-syncs idempotent:
    the same wall-clock day is not pulled twice with different ranges.

    Example:
        ``sync_garmin_data(db, client, days_back=7).skipped_datasets``
    """
    if as_of is None:
        as_of = latest_local_date(db) or date.today()
    start_date = as_of - timedelta(days=days_back)

    # Short-circuit if the client is reporting an MFA challenge.
    if getattr(client, "_pending_mfa", False):
        return SyncReport(needs_mfa=True)

    report = SyncReport()
    for dataset in _SYNC_DATASETS:
        count = _sync_dataset(db, client, dataset, start_date, as_of)
        if count is None:
            report.skipped_datasets.append(dataset.name)
            continue
        setattr(report, dataset.name, count)

    db.flush()
    report.newest_date = latest_local_date(db)
    db.commit()
    return report
