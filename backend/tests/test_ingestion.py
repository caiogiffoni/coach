"""
Ingestion tests — run the export import against the real Garmin GDPR export
at ../temp/garmin_info/ using the same in-memory DB override as test_auth.py.
"""

import json
import zipfile
from datetime import date
from pathlib import Path

import pytest
from conftest import EXPORT, make_session
from sqlalchemy import func, select

from app.ingestion.export_import import import_export
from app.ingestion.models import (
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

MODELS = [
    Activity,
    DailyWellness,
    Sleep,
    Hrv,
    Vo2Max,
    RacePrediction,
    TrainingLoad,
    TrainingReadiness,
    TrainingHistory,
    PersonalRecord,
]


pytestmark = pytest.mark.realdata


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------------------
# Headline numbers (documented in temp/CLAUDE.md)
# ---------------------------------------------------------------------------


def test_activities_count(imported):
    db, report = imported
    assert report.activities == 1223
    assert count(db, Activity) == 1223


def test_sleep_count(imported):
    db, report = imported
    # 1563 raw rows; 15 have a null calendarDate and are skipped (they carry
    # no usable data and have no natural key). temp/CLAUDE.md documents 1549
    # because pandas' drop_duplicates keeps one NaN-keyed row; the real
    # nightly count is 1548 unique dates.
    assert report.sleep == 1548
    assert count(db, Sleep) == 1548


def test_daily_wellness_count(imported):
    db, report = imported
    assert report.daily_wellness >= 1500
    assert count(db, DailyWellness) == report.daily_wellness


def test_other_datasets_populated(imported):
    db, _ = imported
    assert count(db, Hrv) > 100
    assert count(db, Vo2Max) > 400
    assert count(db, RacePrediction) > 0
    assert count(db, TrainingLoad) > 0
    assert count(db, TrainingReadiness) > 0
    assert count(db, TrainingHistory) > 0
    assert count(db, PersonalRecord) > 0


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def test_activity_units_converted(imported):
    db, _ = imported
    # Raw: distance 909625.0 cm, duration 3405367.92 ms, elevationGain 2100 cm
    act = db.scalar(select(Activity).where(Activity.activity_id == 22699918602))
    assert act is not None
    assert act.distance_km == pytest.approx(9.09625)
    assert act.duration_min == pytest.approx(3405367.92 / 60_000, rel=1e-4)
    assert act.elevation_gain_m == pytest.approx(21.0)
    assert act.avg_hr == 158.0
    assert act.start_time_gmt is not None
    assert act.start_time_local is not None


def test_biometric_profile_units(imported):
    db, report = imported
    assert report.biometric_profile == 1
    profile = db.scalar(select(BiometricProfile))
    assert profile.weight_kg == pytest.approx(64.5)  # raw 64500 g
    assert profile.height_cm == pytest.approx(168.0)
    assert profile.lactate_threshold_hr == 185
    assert profile.vo2max == pytest.approx(50.0)


def test_sleep_totals_computed(imported):
    db, _ = imported
    night = db.scalar(select(Sleep).where(Sleep.calendar_date == date(2026, 1, 30)))
    assert night is not None
    assert night.total_sleep_s == (
        night.deep_sleep_s + night.light_sleep_s + night.rem_sleep_s
    )
    assert night.overall_score == 72


def test_hrv_sources(imported):
    db, _ = imported
    sources = {row[0] for row in db.execute(select(Hrv.source).distinct())}
    assert sources == {"snapshot", "daily"}
    daily = db.scalar(select(Hrv).where(Hrv.source == "daily").limit(1))
    assert daily.hrv_status is not None


def test_personal_record_date_parsed(imported):
    db, _ = imported
    pr = db.scalar(
        select(PersonalRecord).where(
            PersonalRecord.record_type == "Best 5km Run",
            PersonalRecord.current.is_(True),
        )
    )
    assert pr is not None
    assert pr.value <= 1800  # seconds (17:43)
    assert pr.pr_start_time_gmt is not None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_reimport_is_idempotent(imported):
    db, first = imported
    before = {m.__name__: count(db, m) for m in MODELS}
    second = import_export(EXPORT, db)
    assert second == first
    for m in MODELS:
        assert count(db, m) == before[m.__name__]


# ---------------------------------------------------------------------------
# Zip handling
# ---------------------------------------------------------------------------


def test_import_from_zip(tmp_path):
    root = tmp_path / "garmin_info"
    metrics = root / "DI_CONNECT" / "DI-Connect-Metrics"
    metrics.mkdir(parents=True)
    (metrics / "TrainingReadinessDTO_20260101_20260102_102452306.json").write_text(
        json.dumps([{"calendarDate": "2026-01-01", "score": 55, "level": "MODERATE"}])
    )
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(
            metrics / "TrainingReadinessDTO_20260101_20260102_102452306.json",
            arcname="garmin_info/DI_CONNECT/DI-Connect-Metrics/TrainingReadinessDTO_20260101_20260102_102452306.json",
        )

    db = make_session()
    report = import_export(zip_path, db)
    assert report.training_readiness == 1
    assert report.activities == 0
    assert count(db, TrainingReadiness) == 1


def test_import_missing_path_raises():
    db = make_session()
    with pytest.raises(FileNotFoundError):
        import_export(Path("/nonexistent/export"), db)


# ---------------------------------------------------------------------------
# Endpoint (uses the shared `client` fixture from conftest.py)
# ---------------------------------------------------------------------------


def test_import_endpoint_requires_auth(client):
    resp = client.post("/api/ingestion/import", json={"path": str(EXPORT)})
    assert resp.status_code == 401


def test_import_endpoint_end_to_end(client):
    token = client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    ).json()["token"]
    resp = client.post(
        "/api/ingestion/import",
        json={"path": str(EXPORT)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["activities"] == 1223
    assert body["sleep"] == 1548
    assert body["biometric_profile"] == 1


def test_import_endpoint_bad_path(client):
    token = client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    ).json()["token"]
    resp = client.post(
        "/api/ingestion/import",
        json={"path": "/nonexistent/export"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
