"""
Bulk import of a Garmin GDPR data export into the normalized SQLite store.

Ported from the pandas loaders in temp/utils.py — same glob patterns, same
wrapper unwrapping, same unit conversions:

  activity distance   cm  → km       (÷ 100_000)
  activity duration   ms  → minutes  (÷ 60_000)
  elevation gain      cm  → m        (÷ 100)
  timestamps          ms epoch → datetime (UTC naive; local kept as wall clock)
  profile weight      g   → kg       (÷ 1_000)
  race predictions    seconds (stored as-is)

Accepts either an extracted export directory (containing DI_CONNECT/) or a
.zip of one. All datasets upsert on natural keys, so re-import is idempotent.

Layout: parse/upsert helpers live in ``export_parsing``, per-dataset loaders in
``export_wellness`` and ``export_metrics``; this module is the orchestrator.
"""

import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings

# Re-exported for backwards-compatible imports (api_pull, older callers).
from .export_metrics import (
    _load_race_predictions,
    _load_training_history,
    _load_training_load,
    _load_training_readiness,
    _load_vo2max,
)
from .export_parsing import (  # noqa: F401
    AGGREGATOR,
    FITNESS,
    METRICS,
    WELLNESS,
    _iso_to_dt,
    _ms_to_dt,
    _parse_date,
    _parse_pr_date,
    _read_json,
    _upsert_many,
)
from .export_wellness import (
    _load_activities,
    _load_biometric_profile,
    _load_daily_wellness,
    _load_hrv,
    _load_personal_records,
    _load_sleep,
)
from .models import (
    Activity,
    BiometricProfile,
    DailyWellness,
    Hrv,
    PersonalRecord,
    RacePrediction,
    Sleep,
    TrainingHistory,
    TrainingLoad,
    TrainingReadiness,
    Vo2Max,
)
from .safeguards import extract_zip_safely


class ImportReport(BaseModel):
    activities: int = 0
    daily_wellness: int = 0
    sleep: int = 0
    hrv: int = 0
    vo2max: int = 0
    race_predictions: int = 0
    training_load: int = 0
    training_readiness: int = 0
    training_history: int = 0
    personal_records: int = 0
    biometric_profile: int = 0


# (report field, model, natural key, loader) — upserted in this order.
_DATASETS: tuple[
    tuple[str, type[Any], tuple[str, ...], Callable[[Path], list[dict]]], ...
] = (
    ("activities", Activity, ("activity_id",), _load_activities),
    ("daily_wellness", DailyWellness, ("calendar_date",), _load_daily_wellness),
    ("sleep", Sleep, ("calendar_date",), _load_sleep),
    ("hrv", Hrv, ("calendar_date", "source", "snapshot_time"), _load_hrv),
    ("vo2max", Vo2Max, ("calendar_date", "sport"), _load_vo2max),
    ("race_predictions", RacePrediction, ("calendar_date",), _load_race_predictions),
    ("training_load", TrainingLoad, ("calendar_date",), _load_training_load),
    (
        "training_readiness",
        TrainingReadiness,
        ("calendar_date",),
        _load_training_readiness,
    ),
    (
        "training_history",
        TrainingHistory,
        ("calendar_date", "sport"),
        _load_training_history,
    ),
    (
        "personal_records",
        PersonalRecord,
        ("personal_record_id",),
        _load_personal_records,
    ),
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _find_export_root(path: Path) -> Path:
    """Locate the directory that contains DI_CONNECT/ (handles zip nesting)."""
    if (path / "DI_CONNECT").is_dir():
        return path
    for child in sorted(path.iterdir()):
        if child.is_dir() and (child / "DI_CONNECT").is_dir():
            return child
    raise FileNotFoundError(f"No DI_CONNECT directory found under {path}")


def _upsert_biometric_profile(base: Path, db: Session) -> int:
    """Upsert the single BiometricProfile row; return 1 if present, else 0."""
    profile = _load_biometric_profile(base)
    if profile is None:
        return 0
    obj = db.scalars(select(BiometricProfile)).first()
    if obj is None:
        db.add(BiometricProfile(**profile))
        return 1
    for field, value in profile.items():
        setattr(obj, field, value)
    return 1


def _import_from_root(base: Path, db: Session) -> ImportReport:
    report = ImportReport()
    for field, model, key_fields, loader in _DATASETS:
        setattr(report, field, _upsert_many(db, model, key_fields, loader(base)))
    report.biometric_profile = _upsert_biometric_profile(base, db)
    db.commit()
    return report


def import_export(export_path: Path, db: Session) -> ImportReport:
    """Import a Garmin GDPR export (directory or .zip) into the database."""
    export_path = Path(export_path)
    if not export_path.exists():
        raise FileNotFoundError(f"Export path does not exist: {export_path}")
    if export_path.is_file() and zipfile.is_zipfile(export_path):
        with tempfile.TemporaryDirectory() as tmp:
            extract_zip_safely(
                export_path,
                Path(tmp),
                settings.upload_max_zip_uncompressed_bytes,
                settings.upload_max_zip_uncompressed_ratio,
            )
            return _import_from_root(_find_export_root(Path(tmp)), db)
    return _import_from_root(_find_export_root(export_path), db)
