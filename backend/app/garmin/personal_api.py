"""Garmin Connect Personal API client (read-only, API-key auth).

Garmin's Personal API lets an individual read their own Connect data with a
key created at https://connect.garmin.com/app/settings/personalApiToken
(FAQ: https://developer.garmin.com/gc-developer-program/personal/personal-faq/).
The key is exchanged for a bearer JWT valid for 24 h, with no refresh token.

It covers activities, wellness, HRV, sleep and VO2max, but workouts, the
calendar, training status/readiness and race predictions return 404, so
pushing workouts still goes through the password-login ``RealGarminClient``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

import jwt

from ..ingestion.training_load_calc import (
    CHRONIC_LOOKBACK_DAYS,
    training_load_from_activities,
)
from .client import GarminDataSource

PERSONAL_API_HOST = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
# Garmin's own sample client renews once less than an hour remains.
TOKEN_RENEW_MARGIN = timedelta(hours=1)
FALLBACK_TOKEN_TTL = timedelta(hours=23)
ACTIVITY_PAGE_SIZE = 100
HTTP_TIMEOUT_S = 30


class PersonalApiError(RuntimeError):
    """Non-2xx response from the Personal API (never includes key or token)."""

    def __init__(self, status: int, path: str, body: str) -> None:
        super().__init__(
            f"Garmin Personal API {path} returned HTTP {status}: {body[:200]}"
        )
        self.status = status


class PersonalApiTransport(Protocol):
    """HTTP seam: tests inject a fake, production uses ``UrllibPersonalApiTransport``."""

    def post_token(self, api_key: str) -> str:
        """Exchange the API key for a bearer JWT (the raw response body)."""
        ...

    def get_json(self, path: str, bearer: str) -> object:
        """GET ``path`` (with query string) and return decoded JSON."""
        ...


class UrllibPersonalApiTransport:
    """Stdlib HTTP transport against ``PERSONAL_API_HOST``."""

    def __init__(self, host: str = PERSONAL_API_HOST) -> None:
        self.host = host

    def _send(self, method: str, path: str, headers: dict[str, str]) -> str:
        req = urllib.request.Request(self.host + path, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                raw: bytes = resp.read()
                return raw.decode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise PersonalApiError(exc.code, path, body) from exc

    def post_token(self, api_key: str) -> str:
        # No Accept header: the token comes back as text/plain and the endpoint
        # answers 406 Not Acceptable to "Accept: application/json".
        return self._send(
            "POST", TOKEN_PATH, {"Authorization": f"ApiKey {api_key}"}
        ).strip()

    def get_json(self, path: str, bearer: str) -> object:
        headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        body = self._send("GET", path, headers)
        return json.loads(body) if body else None


@dataclass(frozen=True)
class _BearerToken:
    value: str
    expires_at: datetime


def _token_expiry(token: str, now: datetime) -> datetime:
    """``exp`` claim of the JWT; signature is Garmin's to check, not ours."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        return datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return now + FALLBACK_TOKEN_TTL


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PersonalApiGarminClient(GarminDataSource):
    """Read Garmin Connect data with a Personal API key.

    Example:
        ``PersonalApiGarminClient(key, UrllibPersonalApiTransport()).get_hrv(d1, d2)``
    """

    def __init__(
        self,
        api_key: str,
        transport: PersonalApiTransport,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._api_key = api_key
        self._transport = transport
        self._clock = clock
        self._token: _BearerToken | None = None

    def _bearer(self) -> str:
        now = self._clock()
        if self._token is None or self._token.expires_at - now < TOKEN_RENEW_MARGIN:
            value = self._transport.post_token(self._api_key)
            self._token = _BearerToken(value, _token_expiry(value, now))
        return self._token.value

    def _get(self, path: str) -> Any:
        try:
            return self._transport.get_json(path, self._bearer())
        except PersonalApiError as exc:
            if exc.status == 401:
                self._token = (
                    None  # key rotated or token revoked: re-exchange next call
                )
            raise

    def _activity_page(self, start_date: date, end_date: date, offset: int) -> list:
        page = self._get(
            "/activitylist-service/activities/search/activities"
            f"?start={offset}&limit={ACTIVITY_PAGE_SIZE}"
            f"&startDate={start_date}&endDate={end_date}"
        )
        return page if isinstance(page, list) else []

    def get_activities(self, start_date: date, end_date: date) -> list[dict]:
        activities: list[dict] = []
        while True:
            page = self._activity_page(start_date, end_date, len(activities))
            activities.extend(page)
            if len(page) < ACTIVITY_PAGE_SIZE:
                return activities

    def get_daily_wellness(self, start_date: date, end_date: date) -> list[dict]:
        """Flat ``usersummary/daily`` rows — the v2 range endpoint is nested."""
        days = (end_date - start_date).days + 1
        dates = (start_date + timedelta(days=i) for i in range(days))
        summaries = (
            self._get(f"/usersummary-service/usersummary/daily?calendarDate={d}")
            for d in dates
        )
        return [s for s in summaries if isinstance(s, dict)]

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        result = self._get(f"/hrv-service/hrv/daily/{start_date}/{end_date}")
        summaries = result.get("hrvSummaries") if isinstance(result, dict) else None
        return summaries if isinstance(summaries, list) else []

    def get_sleep(self, start_date: date, end_date: date) -> list[dict]:
        result = self._get(
            "/sleep-service/sleep/dailySleepSummariesByDate"
            f"?startDate={start_date}&endDate={end_date}"
        )
        return result if isinstance(result, list) else []

    def get_vo2max(self, start_date: date, end_date: date) -> list[dict]:
        result = self._get(
            f"/metrics-service/metrics/maxmet/daily/{start_date}/{end_date}"
        )
        return result if isinstance(result, list) else []

    def get_training_load(self, start_date: date, end_date: date) -> list[dict]:
        """Rebuilt from per-activity load; training status itself is not exposed."""
        lookback_start = start_date - timedelta(days=CHRONIC_LOOKBACK_DAYS)
        activities = self.get_activities(lookback_start, end_date)
        return training_load_from_activities(activities, start_date, end_date)

    def get_training_readiness(self, start_date: date, end_date: date) -> list[dict]:
        """The Personal API has no readiness endpoint (404); nothing to read."""
        return []
