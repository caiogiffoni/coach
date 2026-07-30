"""
Profile endpoint tests.

Seeding tests use a module-scoped client whose DB already contains the real
Garmin export (same fixture pattern as test_ingestion.py); they run in file
order and share that profile.
"""

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.ingestion.export_import import import_export
from app.main import app
from conftest import EXPORT, make_session


@pytest.fixture(scope="module")
def data_client():
    """TestClient backed by an in-memory DB pre-loaded with the real export."""
    db = make_session()
    import_export(EXPORT, db)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    db.close()


def register(client) -> dict[str, str]:
    """Auth headers; registers on first use, logs in if already registered."""
    creds = {"email": "caio@example.com", "password": "secret123"}
    resp = client.post("/api/auth/register", json=creds)
    if resp.status_code != 201:
        resp = client.post("/api/auth/login", json=creds)
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---------------------------------------------------------------------------
# Auth + 404s
# ---------------------------------------------------------------------------


def test_endpoints_require_auth(client):
    assert client.get("/api/profile").status_code == 401
    assert client.put("/api/profile", json={}).status_code == 401
    assert client.post("/api/profile/seed").status_code == 401
    assert client.get("/api/profile/zones").status_code == 401


def test_get_profile_404_before_creation(client):
    resp = client.get("/api/profile", headers=register(client))
    assert resp.status_code == 404


def test_zones_404_without_profile(client):
    resp = client.get("/api/profile/zones", headers=register(client))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT create / partial update / validation
# ---------------------------------------------------------------------------


def test_put_creates_profile(client):
    headers = register(client)
    resp = client.put(
        "/api/profile",
        json={"max_hr": 192, "resting_hr": 47, "goal_mode": "health"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_hr"] == 192
    assert body["resting_hr"] == 47
    assert body["goal_mode"] == "health"
    assert body["injury_history"] == []
    assert body["seeded_at"] is None

    fetched = client.get("/api/profile", headers=headers).json()
    assert fetched == body


def test_put_partial_update_keeps_other_fields(client):
    headers = register(client)
    client.put("/api/profile", json={"max_hr": 190, "resting_hr": 48}, headers=headers)
    resp = client.put("/api/profile", json={"resting_hr": 50}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["resting_hr"] == 50
    assert body["max_hr"] == 190


def test_put_race_mode_requires_race_fields(client):
    headers = register(client)
    resp = client.put("/api/profile", json={"goal_mode": "race"}, headers=headers)
    assert resp.status_code == 422


def test_put_race_mode_with_fields_ok(client):
    headers = register(client)
    resp = client.put(
        "/api/profile",
        json={
            "goal_mode": "race",
            "goal_race_distance": "10K",
            "goal_race_date": "2026-10-11",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["goal_race_distance"] == "10K"


def test_put_rejects_invalid_values(client):
    headers = register(client)
    assert (
        client.put("/api/profile", json={"goal_mode": "ultra"}, headers=headers).status_code
        == 422
    )
    assert (
        client.put(
            "/api/profile", json={"goal_race_distance": "100K"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.put("/api/profile", json={"preferred_days": [7]}, headers=headers).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# Seeding from the real export
# ---------------------------------------------------------------------------


def test_seed_409_without_imported_data(client):
    resp = client.post("/api/profile/seed", headers=register(client))
    assert resp.status_code == 409


def test_seed_populates_from_import(data_client):
    headers = register(data_client)
    resp = data_client.post("/api/profile/seed", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["threshold_hr"] == 185  # BiometricProfile.lactate_threshold_hr
    assert 40 <= body["resting_hr"] <= 60  # athlete RHR ~47
    assert body["max_hr"] >= 185
    assert body["current_weekly_volume_km"] > 0
    assert body["threshold_pace_sec_per_km"] is not None
    assert body["recent_race_distance_km"] is not None
    assert body["recent_race_time_sec"] is not None
    assert body["preferred_days"]
    assert all(0 <= d <= 6 for d in body["preferred_days"])
    assert body["seeded_at"] is not None
    # Goal fields stay manual.
    assert body["goal_mode"] == "health"


def test_seed_does_not_overwrite_manual_edits(data_client):
    headers = register(data_client)
    resp = data_client.put("/api/profile", json={"resting_hr": 50}, headers=headers)
    assert resp.status_code == 200

    resp = data_client.post("/api/profile/seed", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["resting_hr"] == 50  # manual value preserved
    assert body["threshold_hr"] == 185  # seeded value untouched


def test_zones_after_seed_are_sane(data_client):
    headers = register(data_client)
    resp = data_client.get("/api/profile/zones", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["hr_source"] == "lthr"
    hr = body["hr_zones"]
    assert [z["zone"] for z in hr] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    mins = [z["min_bpm"] for z in hr]
    assert mins == sorted(mins)
    for z in hr:
        assert z["min_bpm"] < z["max_bpm"]

    pace = {z["name"]: z for z in body["pace_zones"]}
    assert set(pace) == {"easy", "marathon", "threshold", "interval", "repetition"}
    ordered = ["repetition", "interval", "threshold", "marathon", "easy"]
    for faster, slower in zip(ordered, ordered[1:]):
        assert pace[faster]["max_sec_per_km"] < pace[slower]["min_sec_per_km"]

    assert body["weekly_ceiling_km"] == pytest.approx(
        body["intensity_budget_km"] * 1.10 / 0.20, rel=0.02
    )
    assert body["intensity_budget_km"] > 0
