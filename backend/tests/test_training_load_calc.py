"""Daily acute/chronic load rebuilt from per-activity ``activityTrainingLoad``."""

from datetime import date

from app.ingestion.api_transform import _transform_training_load
from app.ingestion.training_load_calc import (
    acwr_status,
    training_load_from_activities,
)


def _activity(local_start: str, load: float | None) -> dict:
    return {"startTimeLocal": local_start, "activityTrainingLoad": load}


def test_acute_is_seven_day_sum_and_chronic_is_average_week():
    activities = [
        _activity("2026-10-13 07:00:00", 999.0),  # 28 days back: outside chronic
        _activity("2026-10-14 07:00:00", 100.0),  # first chronic day
        _activity("2026-11-03 18:30:00", 60.0),  # 7 days back: outside acute
        _activity("2026-11-04 07:00:00", 80.0),  # first acute day
        _activity("2026-11-10 07:00:00", 40.0),
        _activity("2026-11-10 19:00:00", 20.0),  # second activity same day adds up
    ]

    rows = training_load_from_activities(
        activities, date(2026, 11, 10), date(2026, 11, 10)
    )

    assert rows == [
        {
            "calendarDate": "2026-11-10",
            "dailyTrainingLoadAcute": 140.0,
            "dailyTrainingLoadChronic": 75.0,  # (100 + 60 + 80 + 40 + 20) / 4
            "dailyAcuteChronicWorkloadRatio": 1.87,
            "acwrStatus": "HIGH",
        }
    ]


def test_one_row_per_day_in_range_including_rest_days():
    activities = [_activity("2026-11-01 07:00:00", 50.0)]

    rows = training_load_from_activities(
        activities, date(2026, 11, 1), date(2026, 11, 3)
    )

    assert [r["calendarDate"] for r in rows] == [
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
    ]
    assert [r["dailyTrainingLoadAcute"] for r in rows] == [50.0, 50.0, 50.0]


def test_no_chronic_load_gives_no_ratio():
    rows = training_load_from_activities([], date(2026, 11, 1), date(2026, 11, 1))

    assert rows[0]["dailyTrainingLoadChronic"] == 0.0
    assert rows[0]["dailyAcuteChronicWorkloadRatio"] is None
    assert rows[0]["acwrStatus"] is None


def test_activities_without_load_or_start_are_ignored():
    activities = [
        _activity("2026-11-01 07:00:00", None),
        {"activityTrainingLoad": 30.0},
        _activity("not-a-date", 30.0),
    ]

    rows = training_load_from_activities(
        activities, date(2026, 11, 1), date(2026, 11, 1)
    )

    assert rows[0]["dailyTrainingLoadAcute"] == 0.0


def test_acwr_status_bands():
    assert acwr_status(None) is None
    assert acwr_status(0.79) == "LOW"
    assert acwr_status(0.8) == "OPTIMAL"
    assert acwr_status(1.49) == "OPTIMAL"
    assert acwr_status(1.5) == "HIGH"
    assert acwr_status(2.0) == "VERY_HIGH"


def test_rows_feed_the_existing_training_load_transform():
    rows = training_load_from_activities(
        [_activity("2026-11-01 07:00:00", 50.4)], date(2026, 11, 1), date(2026, 11, 1)
    )

    assert _transform_training_load(rows) == [
        {
            "calendar_date": date(2026, 11, 1),
            "acute_load": 50,
            "chronic_load": 12,
            "acwr": 4.0,
            "acwr_status": "VERY_HIGH",
        }
    ]
