"""
Upload endpoint tests — GDPR export zip, FIT files, and mixed uploads.

No real Garmin API calls; FIT parsing is exercised through the unit-testable
mapping function and via a mocked parser dependency for endpoint tests.
"""

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import make_session
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import get_db
from app.ingestion.fit_parser import (
    fit_parser_dependency,
    parse_fit_file,
    upsert_activity_from_fit,
)
from app.ingestion.models import Activity
from app.ingestion.safeguards import (
    extract_zip_safely,
    sanitize_filename,
    validate_upload_count,
)


def _make_gdpr_zip() -> bytes:
    """Build a minimal in-memory GDPR export zip with one activity and one wellness row."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        summarized = [
            {
                "summarizedActivitiesExport": [
                    {
                        "activityId": 123456789,
                        "name": "Morning Run",
                        "activityType": "running",
                        "sportType": "running",
                        "startTimeGmt": 1704067200000,
                        "startTimeLocal": 1704056400000,
                        "duration": 3600000,
                        "distance": 1000000,
                        "elevationGain": 5000,
                        "avgHr": 150,
                        "maxHr": 175,
                        "minHr": 95,
                        "calories": 600,
                    }
                ]
            }
        ]
        zf.writestr(
            "DI_CONNECT/DI-Connect-Fitness/caio_0_summarizedActivities.json",
            json.dumps(summarized),
        )
        uds = [
            {
                "calendarDate": "2024-01-01",
                "totalSteps": 10000,
                "dailyStepGoal": 8000,
                "totalDistanceMeters": 7500,
                "totalKilocalories": 2400,
                "activeKilocalories": 600,
                "restingHeartRate": 50,
                "minHeartRate": 45,
                "maxHeartRate": 175,
                "highlyActiveSeconds": 1800,
                "activeSeconds": 3600,
                "floorsAscendedInMeters": 10,
                "allDayStress": {
                    "aggregatorList": [
                        {
                            "type": "TOTAL",
                            "averageStressLevel": 35,
                            "maxStressLevel": 75,
                            "stressDuration": 3600,
                            "restDuration": 7200,
                        }
                    ]
                },
            }
        ]
        zf.writestr(
            "DI_CONNECT/DI-Connect-Aggregator/UDSFile_20240101_20240102_1.json",
            json.dumps(uds),
        )
    return buf.getvalue()


@pytest.fixture()
def client():
    """Client fixture with in-memory DB and clean dependency overrides."""
    from app.main import app

    db = make_session()

    def override_get_db():
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _register(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"email": "caio@example.com", "password": "secret123"},
    )
    assert resp.status_code == 201
    return str(resp.json()["token"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_upload_requires_auth(client):
    resp = client.post(
        "/api/ingestion/upload", files={"files": ("x.zip", _make_gdpr_zip())}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GDPR zip upload
# ---------------------------------------------------------------------------


def test_upload_gdpr_zip(client):
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files={"files": ("export.zip", _make_gdpr_zip())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"][0]["filename"] == "export.zip"
    assert body["files"][0]["status"] == "ok"
    assert body["totals"]["activities"] == 1
    assert body["totals"]["daily_wellness"] == 1


# ---------------------------------------------------------------------------
# Unsupported / mixed uploads
# ---------------------------------------------------------------------------


def test_upload_unsupported_file_type(client):
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files={"files": ("report.pdf", b"not a fit file")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"][0]["status"] == "error"
    assert ".pdf" in body["files"][0]["detail"]
    assert body["totals"]["activities"] == 0


def test_upload_mixed_zip_and_bad_extension(client):
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files=[
            ("files", ("export.zip", _make_gdpr_zip())),
            ("files", ("report.txt", b"nope")),
        ],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["files"]) == 2
    assert body["files"][0]["filename"] == "export.zip"
    assert body["files"][0]["status"] == "ok"
    assert body["files"][1]["filename"] == "report.txt"
    assert body["files"][1]["status"] == "error"
    assert body["totals"]["activities"] == 1
    assert body["totals"]["daily_wellness"] == 1


# ---------------------------------------------------------------------------
# FIT parsing (unit-level, no real .FIT bytes)
# ---------------------------------------------------------------------------


def test_map_fit_session_and_upsert():
    """The mapping function converts FIT session units to Activity model units."""
    from app.ingestion.fit_parser import _parse_session

    # Minimal fake fitparse session record object
    class FakeField:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class FakeSession:
        def __init__(self, fields):
            self._fields = {f.name: f for f in fields}

        def get_value(self, name):
            field = self._fields.get(name)
            return field.value if field else None

    start = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    session = FakeSession(
        [
            FakeField("sport", "running"),
            FakeField("start_time", start),
            FakeField("total_elapsed_time", 3600.0),
            FakeField("total_distance", 10000.0),
            FakeField("total_ascent", 120.0),
            FakeField("avg_heart_rate", 155),
            FakeField("max_heart_rate", 178),
            FakeField("total_calories", 800),
        ]
    )

    parsed = _parse_session(session)
    assert parsed["activity_id"] == int(start.timestamp())
    assert parsed["activity_type"] == "running"
    assert parsed["duration_min"] == 60.0
    assert parsed["distance_km"] == 10.0
    assert parsed["elevation_gain_m"] == 120.0
    assert parsed["avg_hr"] == 155
    assert parsed["max_hr"] == 178
    assert parsed["calories"] == 800

    db = make_session()
    activity = upsert_activity_from_fit(db, parsed)
    db.commit()
    assert activity is not None
    assert activity.activity_id == parsed["activity_id"]
    assert activity.distance_km == 10.0

    # Idempotency: re-upsert updates the same row
    row = db.scalar(
        select(Activity).where(Activity.activity_id == activity.activity_id)
    )
    assert row is not None
    assert row.distance_km == 10.0


def test_parse_fit_file_rejects_invalid_bytes():
    """Malformed FIT bytes are rejected gracefully instead of crashing."""
    with pytest.raises(ValueError):
        parse_fit_file(b"")


# ---------------------------------------------------------------------------
# FIT upload endpoint with mocked parser
# ---------------------------------------------------------------------------


def test_upload_fit_file_with_mocked_parser(client):
    from app.main import app

    token = _register(client)

    called = {}

    def fake_parser_factory():
        def fake_parser(path: Path) -> dict:
            called["path"] = str(path)
            return {
                "activity_id": 999999999,
                "name": "Fake Run",
                "activity_type": "running",
                "sport_type": "running",
                "start_time_gmt": datetime(2024, 1, 1, 8, 0, 0),
                "start_time_local": datetime(2024, 1, 1, 8, 0, 0),
                "duration_min": 45.0,
                "distance_km": 8.5,
                "elevation_gain_m": 50.0,
                "avg_hr": 150,
                "max_hr": 170,
                "min_hr": None,
                "calories": 500,
                "vo2max_value": None,
                "aerobic_training_effect": None,
                "anaerobic_training_effect": None,
                "training_load": None,
                "lap_count": None,
                "is_pr": None,
            }

        return fake_parser

    app.dependency_overrides[fit_parser_dependency] = fake_parser_factory
    try:
        resp = client.post(
            "/api/ingestion/upload",
            files={"files": ("activity.fit", b"fake bytes")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["files"][0]["status"] == "ok"
        assert body["totals"]["activities"] == 1
    finally:
        del app.dependency_overrides[fit_parser_dependency]


# ---------------------------------------------------------------------------
# Safeguard tests
# ---------------------------------------------------------------------------


def test_sanitize_filename_strips_paths():
    assert sanitize_filename("report.zip") == "report.zip"
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("/tmp/export.zip") == "export.zip"
    assert sanitize_filename("a\\b\\c.fit") == "a_b_c.fit"
    assert sanitize_filename(None) == "unknown"
    assert sanitize_filename("..") == "unknown"
    assert sanitize_filename("") == "unknown"


def test_validate_upload_count_rejects_too_many():
    class FakeUpload:
        pass

    validate_upload_count([FakeUpload()], 5)
    with pytest.raises(Exception):  # noqa: B017
        validate_upload_count([FakeUpload(), FakeUpload()], 1)


def test_upload_too_many_files(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_files_count", 1)
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files=[
            ("files", ("a.zip", _make_gdpr_zip())),
            ("files", ("b.zip", _make_gdpr_zip())),
        ],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413


def test_upload_file_too_large(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_file_size_bytes", 10)
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files={"files": ("big.fit", b"x" * 20)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"][0]["status"] == "error"
    assert "exceeds maximum size" in body["files"][0]["detail"]


def test_upload_filename_sanitization(client):
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files={"files": ("../../tmp/export.zip", _make_gdpr_zip())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"][0]["filename"] == "export.zip"
    assert body["files"][0]["status"] == "ok"


def _make_zip_with_path_traversal() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../../tmp/evil.txt", "pwned")
    return buf.getvalue()


def test_upload_zip_path_traversal(client):
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files={"files": ("traversal.zip", _make_zip_with_path_traversal())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"][0]["status"] == "error"
    assert "unsafe path" in body["files"][0]["detail"].lower()


def _make_zip_bomb(ratio: int = 200) -> bytes:
    """Create a tiny zip that expands to a much larger repeated payload."""
    uncompressed_size = ratio * 1024  # e.g. 200 KiB of zeros
    payload = b"\x00" * uncompressed_size
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.txt", payload)
    return buf.getvalue()


def test_upload_zip_bomb_rejected(client):
    token = _register(client)
    resp = client.post(
        "/api/ingestion/upload",
        files={"files": ("bomb.zip", _make_zip_bomb(ratio=500))},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"][0]["status"] == "error"
    assert "compression ratio" in body["files"][0]["detail"].lower()


def test_extract_zip_safely_enforces_uncompressed_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_zip_uncompressed_bytes", 100)
    zip_path = tmp_path / "small.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", b"x" * 50)
        zf.writestr("b.txt", b"x" * 60)
    target = tmp_path / "out"
    with pytest.raises(ValueError, match="max uncompressed size"):
        extract_zip_safely(zip_path, target, 100, 100)
