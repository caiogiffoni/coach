"""Unit tests for the helpers extracted during the ingestion/garmin refactor.

No real network, Garmin or LLM calls: the Garmin library and LLM SDK are
replaced by named fake classes.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.garmin.client import RealGarminClient, _index_steps_by_date
from app.ingestion.api_transform import (
    _as_dict,
    _dated_records,
    _hrv_metric,
    _hrv_row,
)
from app.ingestion.export_import import _upsert_biometric_profile
from app.ingestion.export_metrics import _load_by_date, _vo2max_row
from app.ingestion.export_parsing import (
    METRICS,
    _iter_json_records,
    _scale,
    _sorted_by_date_sport,
    _upsert_many,
    activity_row,
)
from app.ingestion.export_wellness import (
    _daily_wellness_row,
    _hrv_daily_row,
    _hrv_snapshot_row,
)
from app.ingestion.fit_parser import _activity_id_from_start, _first_session
from app.ingestion.models import BiometricProfile, TrainingReadiness
from app.llm.client import KimiClient, LLMError


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


# ---------------------------------------------------------------------------
# export_parsing
# ---------------------------------------------------------------------------


def test_activity_row_converts_units():
    row = activity_row(
        {"activityId": 7, "duration": 1_800_000, "distance": 500_000, "pr": True}
    )
    assert row["activity_id"] == 7
    assert row["duration_min"] == 30.0
    assert row["distance_km"] == 5.0
    assert row["elevation_gain_m"] is None
    assert row["is_pr"] is True


def test_scale_passes_none_through():
    assert _scale(None, 10) is None
    assert _scale(50, 10) == 5.0


def test_iter_json_records_flattens_sorted_files(tmp_path: Path):
    folder = tmp_path / METRICS
    folder.mkdir(parents=True)
    (folder / "X_2.json").write_text(json.dumps([{"n": 2}]))
    (folder / "X_1.json").write_text(json.dumps([{"n": 1}, {"n": 1.5}]))
    records = list(_iter_json_records(tmp_path, f"{METRICS}/X_*.json"))
    assert [r["n"] for r in records] == [1, 1.5, 2]


def test_sorted_by_date_sport_orders_none_sport_first():
    d = date(2025, 1, 1)
    rows = _sorted_by_date_sport({(d, "RUN"): {"s": "RUN"}, (d, None): {"s": None}})
    assert [r["s"] for r in rows] == [None, "RUN"]


def test_upsert_many_inserts_then_updates():
    db = make_db()
    key = ("calendar_date",)
    d = date(2025, 1, 1)
    assert (
        _upsert_many(db, TrainingReadiness, key, [{"calendar_date": d, "score": 1}])
        == 1
    )
    db.flush()  # sessions use autoflush=False; the upsert reads committed rows
    assert (
        _upsert_many(db, TrainingReadiness, key, [{"calendar_date": d, "score": 9}])
        == 1
    )
    db.flush()
    rows = list(db.scalars(select(TrainingReadiness)))
    assert [(r.calendar_date, r.score) for r in rows] == [(d, 9)]
    assert _upsert_many(db, TrainingReadiness, key, []) == 0


# ---------------------------------------------------------------------------
# export loaders
# ---------------------------------------------------------------------------


def test_vo2max_row_source_specific_fields():
    rec = {"calendarDate": "2025-01-01", "sport": "RUN", "maxMet": 14, "activityId": 3}
    assert _vo2max_row(rec, "activity")["max_met"] is None
    assert _vo2max_row(rec, "activity")["activity_id"] == 3
    assert _vo2max_row(rec, "metrics")["max_met"] == 14
    assert _vo2max_row(rec, "metrics")["activity_id"] is None


def test_load_by_date_last_record_wins(tmp_path: Path):
    folder = tmp_path / METRICS
    folder.mkdir(parents=True)
    records = [
        {"calendarDate": "2025-01-02", "v": 1},
        {"calendarDate": None, "v": 2},
        {"calendarDate": "2025-01-01", "v": 3},
        {"calendarDate": "2025-01-02", "v": 4},
    ]
    (folder / "Y_1.json").write_text(json.dumps(records))
    rows = _load_by_date(
        tmp_path, "Y_*.json", lambda cal, rec: {"d": cal, "v": rec["v"]}
    )
    assert rows == [{"d": date(2025, 1, 1), "v": 3}, {"d": date(2025, 1, 2), "v": 4}]


def test_daily_wellness_row_unwraps_stress_and_body_battery():
    row = _daily_wellness_row(
        date(2025, 1, 1),
        {
            "totalSteps": 10,
            "allDayStress": {
                "aggregatorList": [{"type": "TOTAL", "maxStressLevel": 80}]
            },
            "bodyBattery": {
                "bodyBatteryStatList": [
                    {"bodyBatteryStatType": "LOWEST", "statsValue": 5}
                ]
            },
        },
    )
    assert (row["total_steps"], row["max_stress"], row["bb_lowest"]) == (10, 80, 5)


def test_hrv_snapshot_and_daily_rows_skip_empty_records():
    assert _hrv_snapshot_row({"calendarDate": "2024-04-01"}) is None
    snapshot = _hrv_snapshot_row(
        {
            "calendarDate": "2024-04-01",
            "summaryTypeDataList": [{"summaryType": "SDRR_HRV", "avgValue": 60}],
        }
    )
    assert snapshot is not None and snapshot["sdrr"] == 60
    assert _hrv_daily_row({"calendarDate": "2025-09-01", "metrics": []}) is None
    daily = _hrv_daily_row(
        {"calendarDate": "2025-09-01", "metrics": [{"type": "HRV", "value": 44}]}
    )
    assert daily is not None and daily["rmssd"] == 44


def test_upsert_biometric_profile_returns_zero_without_file(tmp_path: Path):
    db = make_db()
    assert _upsert_biometric_profile(tmp_path, db) == 0
    assert db.scalars(select(BiometricProfile)).first() is None


# ---------------------------------------------------------------------------
# api_transform
# ---------------------------------------------------------------------------


def test_dated_records_drops_non_dicts_and_missing_dates():
    pairs = _dated_records([1, {"calendarDate": None}, {"calendarDate": "2025-01-01"}])
    assert pairs == [(date(2025, 1, 1), {"calendarDate": "2025-01-01"})]


def test_as_dict_rejects_non_dicts():
    assert _as_dict([1]) == {}
    assert _as_dict(None) == {}
    assert _as_dict({"a": 1}) == {"a": 1}


def test_hrv_metric_prefers_metrics_list_then_flat_summary():
    assert _hrv_metric({"metrics": [{"type": "HRV", "value": 5}]}) == {
        "type": "HRV",
        "value": 5,
    }
    assert _hrv_metric({"value": 7}) == {"value": 7}
    assert _hrv_metric({}) == {}


def test_hrv_row_none_without_rmssd():
    assert _hrv_row(date(2025, 1, 1), {"hrvSummary": {}}) is None
    row = _hrv_row(date(2025, 1, 1), {"rmssd": 30, "status": "LOW"})
    assert row is not None and (row["rmssd"], row["hrv_status"]) == (30, "LOW")


# ---------------------------------------------------------------------------
# fit_parser
# ---------------------------------------------------------------------------


class SessionlessFitFile:
    """Fake fitparse.FitFile with no session messages."""

    def get_messages(self, name: str) -> list:
        return []


class CorruptFitFile:
    """Fake fitparse.FitFile whose message stream raises mid-read."""

    def get_messages(self, name: str):
        raise OSError("truncated record")


def test_activity_id_from_start_handles_datetime_epoch_and_none():
    assert (
        _activity_id_from_start(datetime.fromtimestamp(1_700_000_000)) == 1_700_000_000
    )
    assert _activity_id_from_start(1_700_000_000_000) == 1_700_000_000
    assert _activity_id_from_start(None) is None


def test_first_session_none_and_corrupt(caplog):
    assert _first_session(SessionlessFitFile()) is None
    caplog.set_level(logging.WARNING, logger="app.ingestion.fit_parser")
    with pytest.raises(ValueError, match="truncated record"):
        _first_session(CorruptFitFile())
    assert caplog.records[-1].stage == "read_session"


# ---------------------------------------------------------------------------
# garmin.client (RealGarminClient over a fake garminconnect library)
# ---------------------------------------------------------------------------


class FlakyGarminLibrary:
    """Fake ``garminconnect.Garmin``: stats fail on one day, steps endpoint down."""

    def __init__(self, bad_day: str) -> None:
        self.bad_day = bad_day

    def get_stats(self, cdate: str) -> dict:
        if cdate == self.bad_day:
            raise ValueError("bad json")
        return {"restingHeartRate": 50}

    def get_daily_steps(self, start: str, end: str) -> list:
        raise ValueError("steps 500")


def make_real_client(library: object) -> RealGarminClient:
    client = RealGarminClient("user@example.com", "unused", "/nonexistent")
    client._client = library  # type: ignore[assignment]
    return client


def test_call_per_date_skips_and_logs_failed_day(caplog):
    client = make_real_client(FlakyGarminLibrary(bad_day="2026-06-02"))
    caplog.set_level(logging.WARNING, logger="app.garmin.client")

    rows = client.get_daily_wellness(date(2026, 6, 1), date(2026, 6, 3))

    assert [r["calendarDate"] for r in rows] == ["2026-06-01", "2026-06-03"]
    failed_day = [r for r in caplog.records if getattr(r, "date", None)]
    assert [(r.dataset, r.date) for r in failed_day] == [("get_stats", "2026-06-02")]
    steps = [
        r for r in caplog.records if getattr(r, "dataset", "") == "get_daily_steps"
    ]
    assert "steps 500" in steps[0].error
    assert all("unused" not in r.getMessage() for r in caplog.records)


def test_rows_from_result_shapes():
    unwrap = RealGarminClient._rows_from_result
    assert unwrap({"readiness": {"score": 1}}, "2026-06-01", "readiness") == [
        {"score": 1, "calendarDate": "2026-06-01"}
    ]
    assert unwrap({"readiness": None}, "2026-06-01", "readiness") == []
    assert unwrap([{"a": 1}, 2], "2026-06-01", None) == [
        {"a": 1, "calendarDate": "2026-06-01"},
        2,
    ]
    assert unwrap("text", "2026-06-01", None) == []


def test_index_steps_by_date():
    assert _index_steps_by_date("nope") == {}
    steps = [{"calendarDate": "2026-06-01", "totalSteps": 5}, {"x": 1}]
    assert _index_steps_by_date(steps) == {"2026-06-01": steps[0]}


# ---------------------------------------------------------------------------
# llm.client
# ---------------------------------------------------------------------------


class DownCompletions:
    """Fake ``openai`` chat.completions that always errors."""

    def create(self, **kwargs: object) -> None:
        raise ConnectionError("upstream timeout")


class DownChat:
    completions = DownCompletions()


class DownOpenAI:
    chat = DownChat()


def test_kimi_failure_logged_without_prompt_or_key(caplog):
    client = KimiClient(api_key="sk-secret", base_url="http://localhost", model="k2")
    client._client = DownOpenAI()  # type: ignore[assignment]
    caplog.set_level(logging.WARNING, logger="app.llm.client")

    with pytest.raises(LLMError):
        client.generate("system prompt", "private user prompt")

    (record,) = caplog.records
    assert (record.provider, record.model) == ("Kimi", "k2")
    assert "upstream timeout" in record.error
    text = record.getMessage() + repr(record.__dict__)
    assert "sk-secret" not in text and "private user prompt" not in text
