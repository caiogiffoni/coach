"""Garmin Connect Personal API client: token lifecycle and read endpoints.

``FakePersonalApiTransport`` stands in for HTTP; nothing leaves the process.
"""

from datetime import date, datetime, timedelta, timezone

import jwt
import pytest

from app.garmin.personal_api import (
    PersonalApiError,
    PersonalApiGarminClient,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
START, END = date(2026, 11, 9), date(2026, 11, 10)


def _jwt(expires: datetime) -> str:
    return jwt.encode(
        {"exp": int(expires.timestamp())}, "test-signing-key-32-bytes-long!!"
    )


class FakePersonalApiTransport:
    """Canned responses keyed by path; records every token exchange and GET."""

    def __init__(self, routes: dict[str, object], token_ttl=timedelta(hours=24)):
        self.routes = routes
        self.token_ttl = token_ttl
        self.token_exchanges: list[str] = []
        self.gets: list[tuple[str, str]] = []
        self.fail_with: PersonalApiError | None = None

    def post_token(self, api_key: str) -> str:
        self.token_exchanges.append(api_key)
        return _jwt(NOW + self.token_ttl)

    def get_json(self, path: str, bearer: str) -> object:
        self.gets.append((path, bearer))
        if self.fail_with is not None:
            raise self.fail_with
        if path not in self.routes:
            raise PersonalApiError(404, path, "NOT_FOUND")
        return self.routes[path]


class FakeClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _client(transport, clock=None) -> PersonalApiGarminClient:
    return PersonalApiGarminClient("key-123", transport, clock or FakeClock(NOW))


def _search_path(start: date, end: date, offset: int = 0) -> str:
    return (
        "/activitylist-service/activities/search/activities"
        f"?start={offset}&limit=100&startDate={start}&endDate={end}"
    )


# --- token lifecycle -------------------------------------------------------


def test_token_is_exchanged_once_and_reused_while_fresh():
    transport = FakePersonalApiTransport(
        {"/hrv-service/hrv/daily/2026-11-09/2026-11-10": {"hrvSummaries": []}}
    )
    client = _client(transport)

    client.get_hrv(START, END)
    client.get_hrv(START, END)

    assert transport.token_exchanges == ["key-123"]
    bearer = transport.gets[0][1]
    assert jwt.decode(bearer, options={"verify_signature": False})["exp"]


def test_token_is_renewed_within_an_hour_of_expiry():
    transport = FakePersonalApiTransport(
        {"/hrv-service/hrv/daily/2026-11-09/2026-11-10": {"hrvSummaries": []}}
    )
    clock = FakeClock(NOW)
    client = _client(transport, clock)

    client.get_hrv(START, END)
    clock.now = NOW + timedelta(hours=23, minutes=1)
    client.get_hrv(START, END)

    assert len(transport.token_exchanges) == 2


def test_unauthorized_read_drops_the_cached_token():
    transport = FakePersonalApiTransport({})
    transport.fail_with = PersonalApiError(401, "/hrv", "revoked")
    client = _client(transport)

    with pytest.raises(PersonalApiError):
        client.get_hrv(START, END)
    transport.fail_with = None
    transport.routes["/hrv-service/hrv/daily/2026-11-09/2026-11-10"] = {
        "hrvSummaries": []
    }
    client.get_hrv(START, END)

    assert len(transport.token_exchanges) == 2


def test_error_message_names_status_and_path_but_not_secrets():
    err = PersonalApiError(404, "/workout-service/workouts", '{"error":"NOT_FOUND"}')

    assert "404" in str(err) and "/workout-service/workouts" in str(err)
    assert err.status == 404


# --- read endpoints --------------------------------------------------------


def test_activities_page_until_a_short_page():
    first_page = [{"activityId": i} for i in range(100)]
    transport = FakePersonalApiTransport(
        {
            _search_path(START, END): first_page,
            _search_path(START, END, offset=100): [{"activityId": 100}],
        }
    )

    activities = _client(transport).get_activities(START, END)

    assert len(activities) == 101
    assert len(transport.gets) == 2


def test_daily_wellness_reads_one_user_summary_per_day():
    transport = FakePersonalApiTransport(
        {
            "/usersummary-service/usersummary/daily?calendarDate=2026-11-09": {
                "calendarDate": "2026-11-09",
                "totalSteps": 1,
            },
            "/usersummary-service/usersummary/daily?calendarDate=2026-11-10": {
                "calendarDate": "2026-11-10",
                "totalSteps": 2,
            },
        }
    )

    rows = _client(transport).get_daily_wellness(START, END)

    assert [r["totalSteps"] for r in rows] == [1, 2]


def test_hrv_sleep_and_vo2max_use_range_endpoints():
    hrv = [{"calendarDate": "2026-11-10", "lastNightAvg": 93}]
    sleep = [{"calendarDate": "2026-11-10", "deepSleepSeconds": 1}]
    vo2 = [{"generic": {"calendarDate": "2026-11-10"}, "cycling": None}]
    transport = FakePersonalApiTransport(
        {
            "/hrv-service/hrv/daily/2026-11-09/2026-11-10": {"hrvSummaries": hrv},
            "/sleep-service/sleep/dailySleepSummariesByDate?startDate=2026-11-09&endDate=2026-11-10": sleep,
            "/metrics-service/metrics/maxmet/daily/2026-11-09/2026-11-10": vo2,
        }
    )
    client = _client(transport)

    assert client.get_hrv(START, END) == hrv
    assert client.get_sleep(START, END) == sleep
    assert client.get_vo2max(START, END) == vo2


def test_training_load_is_computed_from_28_days_of_activities():
    lookback_start = START - timedelta(days=27)
    transport = FakePersonalApiTransport(
        {
            _search_path(lookback_start, END): [
                {"startTimeLocal": "2026-10-20 07:00:00", "activityTrainingLoad": 80.0},
                {"startTimeLocal": "2026-11-10 07:00:00", "activityTrainingLoad": 40.0},
            ]
        }
    )

    rows = _client(transport).get_training_load(START, END)

    assert [r["calendarDate"] for r in rows] == ["2026-11-09", "2026-11-10"]
    assert rows[-1]["dailyTrainingLoadAcute"] == 40.0
    assert rows[-1]["dailyTrainingLoadChronic"] == 30.0


def test_training_readiness_is_not_offered_by_the_personal_api():
    transport = FakePersonalApiTransport({})

    assert _client(transport).get_training_readiness(START, END) == []
    assert transport.gets == []


def test_renewal_follows_the_tokens_own_exp_claim():
    transport = FakePersonalApiTransport(
        {"/hrv-service/hrv/daily/2026-11-09/2026-11-10": {"hrvSummaries": []}},
        token_ttl=timedelta(hours=2),
    )
    clock = FakeClock(NOW)
    client = _client(transport, clock)

    client.get_hrv(START, END)
    clock.now = NOW + timedelta(hours=1)  # exactly one hour left: still reused
    client.get_hrv(START, END)
    clock.now = NOW + timedelta(hours=1, seconds=1)
    client.get_hrv(START, END)

    assert len(transport.token_exchanges) == 2


class OpaqueTokenTransport(FakePersonalApiTransport):
    """Returns a token that is not a JWT, so no ``exp`` can be read."""

    def post_token(self, api_key: str) -> str:
        self.token_exchanges.append(api_key)
        return "opaque-token"


def test_token_without_exp_is_assumed_valid_for_23_hours():
    transport = OpaqueTokenTransport(
        {"/hrv-service/hrv/daily/2026-11-09/2026-11-10": {"hrvSummaries": []}}
    )
    clock = FakeClock(NOW)
    client = _client(transport, clock)

    client.get_hrv(START, END)
    clock.now = NOW + timedelta(hours=22)
    client.get_hrv(START, END)
    clock.now = NOW + timedelta(hours=22, seconds=1)
    client.get_hrv(START, END)

    assert len(transport.token_exchanges) == 2
    assert transport.gets[0][1] == "opaque-token"
