"""
Generator + week-plan endpoint tests.

The LLM is always a fake (`FakeLLM`, injected by parameter or FastAPI
dependency override) — no test touches a real API. Endpoint tests run
against the real export import + a seeded profile (conftest fixtures).
"""

import json
from datetime import date, timedelta

import pytest
from conftest import EXPORT, make_session
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_constraints import TARGET, build_db, make_profile, register

from app.coaching.constraints import compute_constraints
from app.coaching.generator import (
    MAX_ATTEMPTS,
    fallback_week,
    fallback_workout,
    generate_day,
    generate_week,
)
from app.coaching.validator import validate_week
from app.db import get_db
from app.ingestion.export_import import import_export
from app.llm.client import get_llm_client
from app.main import app
from app.profile.models import Profile

WEEK = date(2026, 5, 11)  # Monday, used by the endpoint tests


pytestmark = pytest.mark.realdata


class FakeLLM:
    """Canned responses in order; records prompts; 'garbage' when exhausted."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.prompts: list[tuple[str, str]] = []

    def generate(self, prompt_system: str, prompt_user: str) -> str:
        self.prompts.append((prompt_system, prompt_user))
        return self.responses.pop(0) if self.responses else "not json at all"


def canned_week_json(constraints, name_prefix="LLM") -> str:
    """A valid week for `constraints` (fallback-shaped, renamed)."""
    week = fallback_week(constraints)
    for workout in week.workouts:
        workout.name = f"{name_prefix} {workout.name}"
    return week.model_dump_json()


@pytest.fixture()
def constraints():
    db = build_db(volumes=[28.0, 30.0])
    return compute_constraints(db, make_profile(), TARGET)


@pytest.fixture()
def profile():
    return make_profile()


# ---------------------------------------------------------------------------
# Unit: generate_week with a fake LLM
# ---------------------------------------------------------------------------


def test_valid_canned_json_gives_llm_source(constraints, profile):
    llm = FakeLLM([canned_week_json(constraints)])
    result = generate_week(constraints, profile, "notes", llm)
    assert result.source == "llm"
    assert result.errors == []
    assert len(llm.prompts) == 1
    assert {w.date for w in result.week.workouts} == {
        s.date for s in constraints.sessions
    }
    assert validate_week(result.week, constraints) == []


def test_markdown_fenced_json_is_parsed(constraints, profile):
    fenced = f"Here you go!\n```json\n{canned_week_json(constraints)}\n```\n"
    result = generate_week(constraints, profile, None, FakeLLM([fenced]))
    assert result.source == "llm"


def test_garbage_then_valid_retries_with_error_feedback(constraints, profile):
    llm = FakeLLM(["total garbage", canned_week_json(constraints)])
    result = generate_week(constraints, profile, None, llm)
    assert result.source == "llm"
    assert len(llm.prompts) == 2
    assert "VALIDATION ERRORS" in llm.prompts[1][1]
    assert "not valid JSON" in llm.prompts[1][1]


def test_validator_errors_are_fed_back_on_retry(constraints, profile):
    broken = json.loads(canned_week_json(constraints))
    broken["workouts"] = broken["workouts"][:-1]  # drop one day
    llm = FakeLLM([json.dumps(broken), canned_week_json(constraints)])
    result = generate_week(constraints, profile, None, llm)
    assert result.source == "llm"
    assert len(llm.prompts) == 2
    assert "missing workout" in llm.prompts[1][1]


def test_always_garbage_falls_back_to_deterministic_week(constraints, profile):
    llm = FakeLLM(["garbage"] * 10)
    result = generate_week(constraints, profile, None, llm)
    assert result.source == "fallback"
    assert len(llm.prompts) == MAX_ATTEMPTS
    assert validate_week(result.week, constraints) == []
    assert result.errors == []


def test_no_client_falls_back_without_calling(constraints, profile):
    result = generate_week(constraints, profile, None, None)
    assert result.source == "fallback"
    assert validate_week(result.week, constraints) == []


# ---------------------------------------------------------------------------
# Unit: generate_day (single-day regeneration)
# ---------------------------------------------------------------------------


def test_generate_day_replaces_only_that_day(constraints, profile):
    current = fallback_week(constraints)
    slot = constraints.sessions[1]
    canned = fallback_workout(slot).model_copy(update={"name": "LLM special"})
    llm = FakeLLM([canned.model_dump_json()])

    result = generate_day(slot, constraints, profile, None, llm, current)
    assert result.source == "llm"
    by_date = {w.date: w for w in result.week.workouts}
    assert by_date[slot.date].name == "LLM special"
    for w in current.workouts:
        if w.date != slot.date:
            assert by_date[w.date].name == w.name


def test_generate_day_falls_back_when_llm_fails(constraints, profile):
    current = fallback_week(constraints)
    slot = constraints.sessions[0]
    llm = FakeLLM(["garbage"] * 10)
    result = generate_day(slot, constraints, profile, None, llm, current)
    assert result.source == "fallback"
    assert validate_week(result.week, constraints) == []


# ---------------------------------------------------------------------------
# Endpoints (real export + seeded profile, fake LLM via dependency override)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def data_client():
    db = make_session()
    import_export(EXPORT, db)
    holder = {"llm": None}

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_client] = lambda: holder["llm"]
    client = TestClient(app)
    client.post("/api/profile/seed", headers=register(client))
    yield client, db, holder
    app.dependency_overrides.clear()
    db.close()


def _constraints_for(db) -> "object":
    profile = db.scalar(select(Profile))
    return compute_constraints(db, profile, WEEK)


def test_generate_requires_auth(client):
    resp = client.post("/api/coaching/weeks/generate", json={"week": str(WEEK)})
    assert resp.status_code == 401
    assert client.get("/api/coaching/weeks").status_code == 401
    assert client.get(f"/api/coaching/weeks/{WEEK}").status_code == 401


def test_generate_404_without_profile(client):
    resp = client.post(
        "/api/coaching/weeks/generate",
        json={"week": str(WEEK)},
        headers=register(client),
    )
    assert resp.status_code == 404


def test_generate_409_without_imported_data(client):
    headers = register(client)
    client.put("/api/profile", json={"goal_mode": "health"}, headers=headers)
    resp = client.post(
        "/api/coaching/weeks/generate", json={"week": str(WEEK)}, headers=headers
    )
    assert resp.status_code == 409


def test_generate_get_and_list_week(data_client):
    client, db, holder = data_client
    constraints = _constraints_for(db)
    holder["llm"] = FakeLLM([canned_week_json(constraints)])

    resp = client.post(
        "/api/coaching/weeks/generate",
        json={"week": "2026-05-13", "notes": "legs feel heavy"},  # Wed → Monday
        headers=register(client),
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["week_start"] == str(WEEK)
    assert plan["source"] == "llm"
    assert plan["status"] == "draft"
    assert plan["notes"] == "legs feel heavy"
    assert plan["validation_errors"] == []
    assert len(plan["workouts"]) == len(constraints.sessions)
    for workout in plan["workouts"]:
        assert workout["sport"] == "running"
        assert workout["steps"]
        assert workout["name"].startswith("LLM")

    got = client.get(f"/api/coaching/weeks/{WEEK}", headers=register(client))
    assert got.status_code == 200
    assert got.json()["id"] == plan["id"]

    listing = client.get("/api/coaching/weeks", headers=register(client))
    assert listing.status_code == 200
    assert listing.json() == [
        {"week_start": str(WEEK), "status": "draft", "source": "llm"}
    ]


def test_get_missing_week_is_404(data_client):
    client, _, _ = data_client
    resp = client.get("/api/coaching/weeks/2026-01-05", headers=register(client))
    assert resp.status_code == 404


def test_regenerate_single_day(data_client):
    client, db, holder = data_client
    headers = register(client)
    plan = client.get(f"/api/coaching/weeks/{WEEK}", headers=headers).json()
    constraints = _constraints_for(db)
    slot = constraints.sessions[0]

    canned = fallback_workout(slot).model_copy(update={"name": "Regen special"})
    holder["llm"] = FakeLLM([canned.model_dump_json()])
    resp = client.post(
        "/api/coaching/weeks/generate",
        json={"week": str(WEEK), "day_date": str(slot.date)},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["id"] == plan["id"]  # same draft, one day swapped
    by_date = {w["date"]: w for w in updated["workouts"]}
    assert by_date[str(slot.date)]["name"] == "Regen special"
    old = {w["date"]: w["name"] for w in plan["workouts"]}
    for d, name in old.items():
        if d != str(slot.date):
            assert by_date[d]["name"] == name

    # A date with no session slot is a 404.
    resp = client.post(
        "/api/coaching/weeks/generate",
        json={"week": str(WEEK), "day_date": str(WEEK + timedelta(days=6))},
        headers=headers,
    )
    assert resp.status_code == 404


def test_regenerate_week_replaces_draft(data_client):
    client, db, holder = data_client
    headers = register(client)
    before = client.get(f"/api/coaching/weeks/{WEEK}", headers=headers).json()

    constraints = _constraints_for(db)
    holder["llm"] = FakeLLM([canned_week_json(constraints, name_prefix="V2")])
    resp = client.post(
        "/api/coaching/weeks/generate", json={"week": str(WEEK)}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert all(w["name"].startswith("V2") for w in resp.json()["workouts"])

    # Still exactly one plan for the week (the old draft was replaced).
    listing = client.get("/api/coaching/weeks", headers=headers).json()
    assert len(listing) == 1
    after = client.get(f"/api/coaching/weeks/{WEEK}", headers=headers).json()
    assert len(after["workouts"]) == len(before["workouts"])


def test_generate_falls_back_when_llm_keeps_failing(data_client):
    client, db, holder = data_client
    holder["llm"] = FakeLLM()  # garbage on every attempt
    resp = client.post(
        "/api/coaching/weeks/generate",
        json={"week": str(WEEK)},
        headers=register(client),
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["source"] == "fallback"
    assert plan["validation_errors"] == []


# ---------------------------------------------------------------------------
# Approve endpoint (runs last: flips the shared draft for WEEK to approved)
# ---------------------------------------------------------------------------


def test_approve_requires_auth_and_404s_on_missing_week(data_client):
    client, _, _ = data_client
    assert client.post(f"/api/coaching/weeks/{WEEK}/approve").status_code == 401
    resp = client.post(
        "/api/coaching/weeks/2026-01-05/approve", headers=register(client)
    )
    assert resp.status_code == 404


def test_approve_draft_then_409_on_reapprove(data_client):
    client, _, _ = data_client
    headers = register(client)

    resp = client.post(f"/api/coaching/weeks/{WEEK}/approve", headers=headers)
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["status"] == "approved"
    assert plan["workouts"]  # full plan returned, not just a status flip

    resp = client.post(f"/api/coaching/weeks/{WEEK}/approve", headers=headers)
    assert resp.status_code == 409

    # An approved week can no longer be regenerated as a whole.
    resp = client.post(
        "/api/coaching/weeks/generate", json={"week": str(WEEK)}, headers=headers
    )
    assert resp.status_code == 409
