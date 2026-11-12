"""Transforms fed the payload shapes Garmin Connect actually returns.

Shapes are trimmed copies of real Personal API responses (Nov 2026); the
older sync fakes used export-style shapes that the live API never sends.
"""

from datetime import date, datetime

import pytest

from app.ingestion.api_transform import (
    _transform_activities,
    _transform_daily_wellness,
    _transform_hrv,
    _transform_sleep,
    _transform_vo2max,
)

LIVE_HRV_SUMMARY = {
    "calendarDate": "2026-11-10",
    "weeklyAvg": 90,
    "lastNightAvg": 93,
    "lastNight5MinHigh": 123,
    "baseline": {"lowUpper": 78, "balancedLow": 82, "balancedUpper": 102},
    "status": "BALANCED",
}

EXPECTED_HRV_ROW = {
    "calendar_date": date(2026, 11, 10),
    "source": "daily",
    "snapshot_time": "",
    "rmssd": 93,
    "sdrr": None,
    "hrv_status": "BALANCED",
    "hrv_pct": None,
    "baseline_lo": 82,
    "baseline_hi": 102,
}


def test_hrv_from_range_endpoint_summary():
    assert _transform_hrv([LIVE_HRV_SUMMARY]) == [EXPECTED_HRV_ROW]


def test_hrv_from_single_day_endpoint_wrapper():
    # Regression: /hrv-service/hrv/{date} wraps the summary in "hrvSummary" and
    # has no "metrics"/"rmssd", so the old transform dropped every synced night.
    wrapped = {"calendarDate": "2026-11-10", "hrvSummary": LIVE_HRV_SUMMARY}

    assert _transform_hrv([wrapped]) == [EXPECTED_HRV_ROW]


LIVE_SLEEP = {
    "calendarDate": "2026-11-11",
    "sleepStartTimestampGMT": 1794363165000,
    "sleepEndTimestampGMT": 1794389085000,
    "deepSleepSeconds": 7200,
    "lightSleepSeconds": 14100,
    "remSleepSeconds": 2880,
    "awakeSleepSeconds": 1740,
    "averageRespirationValue": 14.0,
    "avgSleepStress": 9.0,
    "awakeCount": 1,
    "sleepScores": {"overall": {"value": 76, "qualifierKey": "FAIR"}},
}


def test_sleep_from_live_summary():
    assert _transform_sleep([LIVE_SLEEP]) == [
        {
            "calendar_date": date(2026, 11, 11),
            "sleep_start_gmt": datetime(2026, 11, 11, 2, 12, 45),
            "sleep_end_gmt": datetime(2026, 11, 11, 9, 24, 45),
            "deep_sleep_s": 7200,
            "light_sleep_s": 14100,
            "rem_sleep_s": 2880,
            "awake_sleep_s": 1740,
            "total_sleep_s": 24180,
            "average_respiration": 14.0,
            "avg_sleep_stress": 9.0,
            "awake_count": 1,
            "overall_score": 76,
        }
    ]


def test_sleep_skips_nights_without_date():
    assert _transform_sleep([{"deepSleepSeconds": 1}, "junk"]) == []  # type: ignore[list-item]


def test_vo2max_flattens_generic_and_cycling_entries():
    raw = [
        {
            "generic": {
                "calendarDate": "2026-11-04",
                "vo2MaxPreciseValue": 48.1,
                "vo2MaxValue": 48.0,
                "sport": "RUNNING",
            },
            "cycling": None,
        },
        {
            "generic": {"calendarDate": "2026-11-07", "vo2MaxValue": 47.0},
            "cycling": {
                "calendarDate": "2026-11-07",
                "vo2MaxValue": 44.0,
                "sport": "CYCLING",
            },
        },
    ]

    rows = _transform_vo2max(raw)

    assert [(r["calendar_date"], r["sport"], r["vo2max_value"]) for r in rows] == [
        (date(2026, 11, 4), "RUNNING", 48.1),
        (date(2026, 11, 7), None, 47.0),
        (date(2026, 11, 7), "CYCLING", 44.0),
    ]
    assert {r["source"] for r in rows} == {"metrics"}


LIVE_USER_SUMMARY = {
    "calendarDate": "2026-11-10",
    "totalSteps": 914,
    "restingHeartRate": 49,
    "averageStressLevel": 26,
    "maxStressLevel": 87,
    "stressDuration": 28320,
    "restStressDuration": 37680,
    "bodyBatteryChargedValue": 92,
    "bodyBatteryDrainedValue": 72,
    "bodyBatteryHighestValue": 99,
    "bodyBatteryLowestValue": 22,
    "bodyBatteryAtWakeTime": 97,
    "bodyBatteryDuringSleep": 72,
}


def test_daily_wellness_reads_flat_user_summary_stress_and_body_battery():
    [row] = _transform_daily_wellness([LIVE_USER_SUMMARY])

    assert (row["total_steps"], row["resting_hr"]) == (914, 49)
    assert (row["avg_stress"], row["max_stress"]) == (26, 87)
    assert (row["stress_duration_s"], row["rest_duration_s"]) == (28320, 37680)
    assert (row["bb_charged"], row["bb_drained"]) == (92, 72)
    assert (row["bb_highest"], row["bb_lowest"]) == (99, 22)
    assert (row["bb_sleep_end"], row["bb_during_sleep"]) == (97, 72)


LIVE_ACTIVITY = {
    "activityId": 22814,
    "activityName": "Easy Run",
    "activityType": {"typeId": 1, "typeKey": "running", "parentTypeId": 17},
    "sportTypeId": 1,
    "startTimeGMT": "2026-11-11 20:36:58",
    "startTimeLocal": "2026-11-11 17:36:58",
    "duration": 3045.28,
    "distance": 6876.86,
    "elevationGain": 36.0,
    "averageHR": 152.0,
    "maxHR": 171.0,
    "minHR": None,
    "calories": 447.0,
    "vO2MaxValue": 48.0,
    "aerobicTrainingEffect": 3.2,
    "anaerobicTrainingEffect": 0.4,
    "activityTrainingLoad": 65.6,
    "lapCount": 7,
    "pr": False,
}


def test_activity_from_live_search_result():
    # Regression: the search endpoint uses seconds/metres, string timestamps and a
    # nested activityType; the export mapper crashed on it ("str / int").
    [row] = _transform_activities([LIVE_ACTIVITY])

    assert row == {
        "activity_id": 22814,
        "name": "Easy Run",
        "activity_type": "running",
        "sport_type": None,
        "start_time_gmt": datetime(2026, 11, 11, 20, 36, 58),
        "start_time_local": datetime(2026, 11, 11, 17, 36, 58),
        "duration_min": pytest.approx(50.755, abs=1e-3),
        "distance_km": pytest.approx(6.877, abs=1e-3),
        "elevation_gain_m": 36.0,
        "avg_hr": 152.0,
        "max_hr": 171.0,
        "min_hr": None,
        "calories": 447.0,
        "vo2max_value": 48.0,
        "aerobic_training_effect": 3.2,
        "anaerobic_training_effect": 0.4,
        "training_load": 65.6,
        "lap_count": 7,
        "is_pr": False,
    }
