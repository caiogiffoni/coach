"""
Constraint engine tests.

Real-export integration tests use the shared conftest fixtures (import +
seeded profile); behavior-focused tests use small synthetic databases so each
scenario (fatigue veto, deload cycle, phases) is hermetic.
"""

from datetime import date, datetime, timedelta

import pytest
from conftest import EXPORT, make_session
from fastapi.testclient import TestClient

from app.coaching.constraints import compute_constraints
from app.db import get_db
from app.ingestion.export_import import import_export
from app.ingestion.models import Activity, DailyWellness
from app.main import app
from app.models import User
from app.profile.models import Profile
from app.profile.seed import seed_profile_from_data

# A Monday used as the default target week across the synthetic tests.
TARGET = date(2026, 6, 1)  # Monday


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.realdata


def make_profile(**overrides) -> Profile:
    """Transient profile (no DB needed — the engine only reads attributes)."""
    values = dict(
        user_id=1,
        max_hr=192,
        resting_hr=47,
        threshold_hr=185,
        threshold_pace_sec_per_km=280,
        current_weekly_volume_km=30.0,
        injury_history=[],
        goal_mode="health",
        preferred_days=[0, 2, 4, 5],
    )
    values.update(overrides)
    return Profile(**values)


_activity_id = 0


def add_run(db, when: datetime, km: float, avg_hr: float | None = None):
    global _activity_id
    _activity_id += 1
    db.add(
        Activity(
            activity_id=_activity_id,
            activity_type="running",
            start_time_local=when,
            start_time_gmt=when,
            duration_min=km * 6,
            distance_km=km,
            avg_hr=avg_hr,
        )
    )


def add_weekly_volume(db, monday: date, km: float):
    """Two runs (Mon + Sun) totalling `km`; Sun keeps the week 'complete'."""
    add_run(db, datetime(monday.year, monday.month, monday.day, 8, 0), km / 2)
    sunday = monday + timedelta(days=6)
    add_run(db, datetime(sunday.year, sunday.month, sunday.day, 8, 0), km / 2)


def build_db(volumes: list[float] | None = None):
    """Synthetic DB with `volumes` km in the weeks before TARGET (oldest first)."""
    db = make_session()
    for i, km in enumerate(volumes or []):
        monday = TARGET - timedelta(weeks=len(volumes) - i)
        add_weekly_volume(db, monday, km)
    db.commit()
    return db


def no_consecutive_pairs(dates: list[date]) -> bool:
    return all((b - a).days > 1 for a, b in zip(dates, dates[1:]))


# ---------------------------------------------------------------------------
# Real export: constraints generate successfully
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_profile():
    db = make_session()
    import_export(EXPORT, db)
    db.add(User(email="caio@example.com", password_hash="x"))
    db.commit()
    profile = seed_profile_from_data(1, db)
    yield db, profile
    db.close()


def test_constraints_generate_from_real_data(real_profile):
    db, profile = real_profile
    c = compute_constraints(db, profile, date(2026, 5, 11))

    assert c.week_start == date(2026, 5, 11)  # already a Monday
    assert c.weekly_volume_target_km > 0
    # Hard guardrail: target never exceeds recent avg × 1.10.
    assert c.weekly_volume_target_km <= c.weekly_volume_ceiling_km + 1e-9
    assert c.weekly_volume_ceiling_km == pytest.approx(
        c.state.avg_weekly_km * 1.10, abs=0.02
    )
    # 80/20 budget when building, zero when deload/vetoed.
    if c.cycle_week_type == "build" and not c.fatigue_veto:
        assert c.intensity_budget_km == pytest.approx(
            0.20 * c.weekly_volume_target_km, abs=0.02
        )
    else:
        assert c.intensity_budget_km == 0.0

    # State snapshot is populated from the imported data.
    assert c.state.avg_weekly_km > 0
    assert c.state.acwr is not None
    assert c.state.readiness_level is not None
    assert c.state.resting_hr_baseline is not None
    assert c.state.sleep_avg_hours_7d is not None
    assert len(c.state.weekly_volumes) == 8

    assert c.sessions
    for slot in c.sessions:
        assert slot.date >= c.week_start
        assert slot.date < c.week_start + timedelta(days=7)
        assert slot.weekday in c.allowed_days
        assert slot.distance_km_lo <= slot.distance_km_hi
    assert c.rationale


# ---------------------------------------------------------------------------
# Fatigue veto (synthetic: latest RHR >10% over 30-day median)
# ---------------------------------------------------------------------------


def test_fatigue_veto_from_elevated_resting_hr():
    db = build_db(volumes=[28.0, 30.0])
    anchor = TARGET - timedelta(days=1)  # latest run (Sunday before TARGET)
    for i in range(9, 0, -1):
        db.add(DailyWellness(calendar_date=anchor - timedelta(days=i), resting_hr=47))
    db.add(DailyWellness(calendar_date=anchor, resting_hr=55))  # +17% over median
    db.commit()

    c = compute_constraints(db, make_profile(), TARGET)
    assert c.fatigue_veto is True
    assert any("Resting HR" in reason for reason in c.fatigue_reasons)
    assert c.intensity_budget_km == 0.0
    assert c.sessions
    for slot in c.sessions:
        assert slot.hr_zone_range == "Z1-Z2"
        assert slot.pace_zone == "easy"


def test_no_veto_when_fresh():
    db = build_db(volumes=[28.0, 30.0])
    c = compute_constraints(db, make_profile(), TARGET)
    assert c.fatigue_veto is False
    assert c.fatigue_reasons == []


# ---------------------------------------------------------------------------
# Injury flags: no back-to-back run days at all
# ---------------------------------------------------------------------------


def test_injury_flag_removes_consecutive_days():
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(injury_history=["IT band syndrome"])
    c = compute_constraints(db, profile, TARGET, days_override=[0, 1, 2, 4])

    assert c.injury_flags == ["IT band syndrome"]
    dates = [s.date for s in c.sessions]
    assert no_consecutive_pairs(dates)
    # [Mon, Tue, Wed, Fri] → Tue dropped (keeps Mon/Wed/Fri).
    assert [d.weekday() for d in dates] == [0, 2, 4]
    assert any("IT band" in r for r in c.rationale)


# ---------------------------------------------------------------------------
# Hard-day limits and long-run cap
# ---------------------------------------------------------------------------


def test_max_two_quality_and_no_back_to_back_hard():
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TARGET + timedelta(weeks=10),
    )
    c = compute_constraints(db, profile, TARGET, days_override=[0, 1, 2, 4, 6])

    hard = [s for s in c.sessions if s.type == "quality"]
    assert len(hard) <= 2
    pairs = zip(c.sessions, c.sessions[1:])
    for a, b in pairs:
        if (b.date - a.date).days == 1:
            assert not (a.type in ("quality", "long") and b.type in ("quality", "long"))


def test_long_run_capped_at_30_percent_of_target():
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TARGET + timedelta(weeks=10),
    )
    c = compute_constraints(db, profile, TARGET)
    long_slots = [s for s in c.sessions if s.type == "long"]
    assert len(long_slots) == 1
    assert long_slots[0].distance_km_hi <= 0.30 * c.weekly_volume_target_km + 0.05


def test_build_week_budget_is_20_percent():
    db = build_db(volumes=[28.0, 30.0])
    profile = make_profile(
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TARGET + timedelta(weeks=10),
    )
    c = compute_constraints(db, profile, TARGET)
    assert c.cycle_week_type == "build"
    assert c.weekly_volume_target_km == pytest.approx(29.0, abs=0.1)
    assert c.intensity_budget_km == pytest.approx(5.8, abs=0.05)


# ---------------------------------------------------------------------------
# 3:1 cycle: deload detection
# ---------------------------------------------------------------------------


def test_three_rising_weeks_trigger_deload():
    db = build_db(volumes=[30.0, 32.0, 34.0])
    c = compute_constraints(db, make_profile(), TARGET)

    assert c.cycle_week_type == "deload"
    # Deload target = last complete week (34 km) × 0.65, under the ceiling.
    assert c.weekly_volume_target_km == pytest.approx(34.0 * 0.65, abs=0.15)
    assert c.intensity_budget_km == 0.0
    for slot in c.sessions:
        assert slot.hr_zone_range == "Z1-Z2"
        assert slot.pace_zone == "easy"


def test_short_history_defaults_to_build():
    db = build_db(volumes=[30.0])
    c = compute_constraints(db, make_profile(), TARGET)
    assert c.cycle_week_type == "build"


# ---------------------------------------------------------------------------
# Phases: race mode vs health mode
# ---------------------------------------------------------------------------


def race_profile(weeks_out: int) -> Profile:
    return make_profile(
        goal_mode="race",
        goal_race_distance="10K",
        goal_race_date=TARGET + timedelta(weeks=weeks_out),
    )


def test_race_phase_base_when_far_out():
    db = build_db(volumes=[28.0, 30.0])
    c = compute_constraints(db, race_profile(12), TARGET)
    assert c.phase in ("base", "build")
    assert c.weeks_to_race == 12


def test_race_phase_taper_two_weeks_out():
    db = build_db(volumes=[28.0, 30.0])
    c = compute_constraints(db, race_profile(2), TARGET)
    assert c.phase == "taper"
    assert c.weeks_to_race == 2


def test_health_mode_has_no_phase_and_stays_easy():
    db = build_db(volumes=[28.0, 30.0])
    c = compute_constraints(db, make_profile(goal_mode="health"), TARGET)

    assert c.phase is None
    assert c.weeks_to_race is None
    assert c.sessions
    assert all(s.type != "quality" for s in c.sessions)
    assert all(s.hr_zone_range in ("Z1-Z1", "Z1-Z2", "Z2-Z3") for s in c.sessions)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def register(client) -> dict[str, str]:
    creds = {"email": "caio@example.com", "password": "secret123"}
    resp = client.post("/api/auth/register", json=creds)
    if resp.status_code != 201:
        resp = client.post("/api/auth/login", json=creds)
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(scope="module")
def data_client():
    db = make_session()
    import_export(EXPORT, db)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.post("/api/profile/seed", headers=register(client))
    yield client
    app.dependency_overrides.clear()
    db.close()


def test_endpoint_requires_auth(client):
    assert client.get("/api/coaching/constraints?week=2026-05-11").status_code == 401


def test_endpoint_404_without_profile(client):
    resp = client.get(
        "/api/coaching/constraints?week=2026-05-11", headers=register(client)
    )
    assert resp.status_code == 404


def test_endpoint_409_without_imported_data(client):
    headers = register(client)
    client.put("/api/profile", json={"goal_mode": "health"}, headers=headers)
    resp = client.get("/api/coaching/constraints?week=2026-05-11", headers=headers)
    assert resp.status_code == 409


def test_endpoint_success_and_monday_normalization(data_client):
    headers = register(data_client)
    # 2026-05-06 is a Wednesday → normalized to Monday 2026-05-04.
    resp = data_client.get("/api/coaching/constraints?week=2026-05-06", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["week_start"] == "2026-05-04"
    assert body["weekly_volume_target_km"] <= body["weekly_volume_ceiling_km"] + 1e-9
    assert body["sessions"]


def test_endpoint_days_override(data_client):
    headers = register(data_client)
    resp = data_client.get(
        "/api/coaching/constraints?week=2026-05-11&days=1,3", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed_days"] == [1, 3]
    assert {s["weekday"] for s in body["sessions"]} <= {1, 3}


def test_endpoint_rejects_bad_days(data_client):
    headers = register(data_client)
    for bad in ("7", "abc", "1,,2", ""):
        resp = data_client.get(
            f"/api/coaching/constraints?week=2026-05-11&days={bad}", headers=headers
        )
        assert resp.status_code == 422, bad
