"""Garmin Connect client wrapper.

Uses the unofficial ``garminconnect`` library (v0.3.x) with ``curl_cffi`` for
TLS impersonation. Per PLAN.md/CLAUDE.md we do **not** use the deprecated
``garth`` library; session persistence is handled by the library's own token
save/load methods (``client.dump`` / ``client.load``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from fastapi import Depends, HTTPException, status
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginResult:
    """Result of a Garmin Connect login attempt."""

    success: bool = False
    needs_mfa: bool = False
    message: str = ""


class GarminClient(Protocol):
    """Dependency-injectable interface for Garmin Connect operations."""

    def login(self, mfa_code: str | None = None) -> LoginResult:
        """Authenticate (or resume with ``mfa_code``)."""
        ...

    def logout(self) -> None:
        """Drop any cached session / pending-MFA state."""
        ...

    def is_logged_in(self) -> bool:
        """Return True when the client has an active session."""
        ...

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        """Upload ``workout_json`` and schedule it to ``target_date``; return Garmin workout ID."""
        ...

    def delete_workout(self, garmin_workout_id: str) -> None:
        """Delete a workout template from the Garmin library."""
        ...

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        """Return workouts already scheduled on ``target_date``.

        Each dict must contain at least ``workoutId`` and ``name``.
        """
        ...

    def get_activities(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch activities between ``start_date`` and ``end_date`` (inclusive)."""
        ...

    def get_daily_wellness(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch daily wellness summaries (steps, RHR, stress, body battery)."""
        ...

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch HRV data for ``start_date`` to ``end_date`` (inclusive)."""
        ...

    def get_training_readiness(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch training readiness scores for the date range."""
        ...

    def get_training_load(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch training status / load data for the date range."""
        ...


class RealGarminClient(GarminClient):
    """Production wrapper around ``garminconnect.Garmin``.

    The underlying ``Garmin`` instance is kept as a singleton so that a
    pending-MFA login can be resumed with the same internal state.
    """

    def __init__(self, email: str, password: str, token_store: str) -> None:
        self.email = email
        self.password = password
        self.token_store = Path(token_store).expanduser()
        self._client: Garmin | None = None
        self._pending_mfa = False

    def login(self, mfa_code: str | None = None) -> LoginResult:
        # Resume an MFA challenge that we previously returned.
        if self._pending_mfa:
            if not mfa_code:
                return LoginResult(
                    needs_mfa=True,
                    message="MFA code required",
                )
            return self._complete_mfa(mfa_code)

        # Fresh login attempt. Create a new instance so stale state is cleared.
        self._client = Garmin(
            self.email,
            self.password,
            return_on_mfa=True,
        )
        try:
            mfa_status, _ = self._client.login(str(self.token_store))
        except GarminConnectAuthenticationError as exc:
            return LoginResult(
                success=False,
                message=f"Authentication failed: {exc}",
            )
        except GarminConnectConnectionError as exc:
            return LoginResult(
                success=False,
                message=f"Could not reach Garmin: {exc}",
            )

        if mfa_status is not None:
            self._pending_mfa = True
            return LoginResult(
                needs_mfa=True,
                message="Enter the MFA code from your authenticator app",
            )

        return LoginResult(success=True, message="Logged in")

    def _complete_mfa(self, mfa_code: str) -> LoginResult:
        if self._client is None:
            return LoginResult(
                success=False,
                message="MFA session expired; start login again",
            )
        try:
            # resume_login uses the internal MFA state stashed on the Client.
            self._client.client.resume_login(None, mfa_code)
            # Persist the now-authenticated tokens.
            self._client.client.dump(str(self.token_store))
        except GarminConnectAuthenticationError as exc:
            return LoginResult(
                success=False,
                message=f"MFA failed: {exc}",
            )
        except GarminConnectConnectionError as exc:
            return LoginResult(
                success=False,
                message=f"Could not reach Garmin: {exc}",
            )
        finally:
            self._pending_mfa = False

        return LoginResult(success=True, message="Logged in")

    def logout(self) -> None:
        self._client = None
        self._pending_mfa = False

    def is_logged_in(self) -> bool:
        if self._client is None:
            return False
        # The underlying Client exposes an authenticated flag.
        return bool(getattr(self._client.client, "is_authenticated", False))

    def _ensure_logged_in(self) -> Garmin:
        if self._client is None:
            raise RuntimeError("Not logged in to Garmin")
        return self._client

    @staticmethod
    def _date_range(start_date: date, end_date: date) -> list[date]:
        days = (end_date - start_date).days
        return [start_date + timedelta(days=i) for i in range(days + 1)]

    def _call(self, name: str, *args, **kwargs):
        """Call an underlying Garmin method, translating connection errors."""
        client = self._ensure_logged_in()
        method = getattr(client, name)
        try:
            return method(*args, **kwargs)
        except GarminConnectConnectionError as exc:
            raise RuntimeError(f"Garmin connection error: {exc}") from exc

    def _call_per_date(
        self,
        method_name: str,
        start_date: date,
        end_date: date,
        key: str | None = None,
    ) -> list[dict]:
        """Call a single-date read method for every date in the range.

        Some Garmin endpoints return a dict keyed by ``calendarDate``; if
        ``key`` is provided we unwrap that key, otherwise we treat the result
        as a single row and inject ``calendarDate`` when missing.
        """
        client = self._ensure_logged_in()
        if not hasattr(client, method_name):
            logger.warning(
                "Garmin method %s not available in this library version", method_name
            )
            return []

        rows: list[dict] = []
        for day in self._date_range(start_date, end_date):
            date_str = day.isoformat()
            try:
                result = self._call(method_name, date_str)
            except (GarminConnectConnectionError, RuntimeError):
                raise
            except Exception as exc:  # noqa: BLE001 — best-effort read; don't crash sync
                logger.warning(
                    "Garmin %s failed for %s: %s", method_name, date_str, exc
                )
                continue

            if result is None:
                continue

            if key:
                payload = result.get(key) if isinstance(result, dict) else None
                if isinstance(payload, dict):
                    payload["calendarDate"] = payload.get("calendarDate", date_str)
                    rows.append(payload)
            elif isinstance(result, dict):
                result["calendarDate"] = result.get("calendarDate", date_str)
                rows.append(result)
            elif isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        item.setdefault("calendarDate", date_str)
                rows.extend(result)
        return rows

    def get_activities(self, start_date: date, end_date: date) -> list[dict]:
        client = self._ensure_logged_in()
        method_name = "get_activities_by_date"
        if not hasattr(client, method_name):
            logger.warning(
                "Garmin method %s not available; skipping activities", method_name
            )
            return []
        try:
            result: list[dict] = self._call(
                method_name,
                start_date.isoformat(),
                end_date.isoformat(),
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Garmin %s failed: %s", method_name, exc)
            return []

    def get_daily_wellness(self, start_date: date, end_date: date) -> list[dict]:
        """Combine daily user summary with step data for the date range.

        Uses ``get_user_summary(cdate)`` for the main wellness row and
        ``get_daily_steps(start, end)`` for step details. Body-battery/stress
        fields come from the summary where available.
        """
        client = self._ensure_logged_in()
        summaries = []
        # get_stats is the older compat name and tends to be the most stable
        # source for RHR/steps; get_user_summary is the newer alias.
        if hasattr(client, "get_stats"):
            summaries = self._call_per_date("get_stats", start_date, end_date)
        elif hasattr(client, "get_user_summary"):
            summaries = self._call_per_date("get_user_summary", start_date, end_date)
        else:
            logger.warning("No daily wellness method available; skipping wellness")
            return []

        steps_by_date: dict[str, dict] = {}
        if hasattr(client, "get_daily_steps"):
            try:
                steps = self._call(
                    "get_daily_steps", start_date.isoformat(), end_date.isoformat()
                )
                if isinstance(steps, list):
                    for item in steps:
                        if isinstance(item, dict) and item.get("calendarDate"):
                            steps_by_date[item["calendarDate"]] = item
            except Exception as exc:  # noqa: BLE001
                logger.warning("Garmin get_daily_steps failed: %s", exc)

        merged: list[dict] = []
        for summary in summaries:
            cal = summary.get("calendarDate")
            if not cal:
                continue
            merged_row = dict(summary)
            steps = steps_by_date.get(cal, {})
            merged_row.update({k: v for k, v in steps.items() if v is not None})
            merged.append(merged_row)
        return merged

    def get_hrv(self, start_date: date, end_date: date) -> list[dict]:
        return self._call_per_date("get_hrv_data", start_date, end_date)

    def get_training_readiness(self, start_date: date, end_date: date) -> list[dict]:
        """Try the daily readiness endpoint; fall back to the morning report."""
        client = self._ensure_logged_in()
        if hasattr(client, "get_training_readiness"):
            return self._call_per_date("get_training_readiness", start_date, end_date)
        if hasattr(client, "get_morning_training_readiness"):
            return self._call_per_date(
                "get_morning_training_readiness", start_date, end_date, key="readiness"
            )
        logger.warning("No training readiness method available; skipping readiness")
        return []

    def get_training_load(self, start_date: date, end_date: date) -> list[dict]:
        """Read training status, which contains acute/chronic load and ACWR."""
        rows = self._call_per_date("get_training_status", start_date, end_date)
        # Garmin sometimes returns a nested dict under "trainingStatus".
        flattened: list[dict] = []
        for row in rows:
            status = row.get("trainingStatus")
            if isinstance(status, dict):
                status.setdefault("calendarDate", row.get("calendarDate"))
                flattened.append(status)
            else:
                flattened.append(row)
        return flattened

    def schedule_workout(self, workout_json: dict, target_date: date) -> str:
        client = self._ensure_logged_in()
        resp = client.upload_workout(workout_json)
        workout_id = str(resp["workoutId"])
        client.schedule_workout(workout_id, target_date.isoformat())
        return workout_id

    def delete_workout(self, garmin_workout_id: str) -> None:
        client = self._ensure_logged_in()
        client.delete_workout(garmin_workout_id)

    def get_workouts_for_date(self, target_date: date) -> list[dict]:
        """Fetch the calendar month and filter to the requested date.

        Garmin's ``get_scheduled_workouts`` returns a whole month; we reduce it
        to a simple list of ``{workoutId, name}`` dicts for collision checks.
        """
        client = self._ensure_logged_in()
        # Garmin's API uses 0-indexed months; the wrapper subtracts 1 internally.
        month_data = client.get_scheduled_workouts(target_date.year, target_date.month)
        date_key = target_date.isoformat()
        items: list[dict] = month_data.get(date_key, [])
        return [
            {
                "workoutId": str(item.get("workoutId")),
                "name": str(item.get("name", "Unknown")),
            }
            for item in items
        ]


@lru_cache(maxsize=1)
def _real_client(email: str, password: str, token_store: str) -> RealGarminClient:
    return RealGarminClient(email, password, token_store)


def get_garmin_client() -> GarminClient | None:
    """FastAPI dependency: returns a cached real client or ``None``.

    Returns ``None`` when Garmin credentials are not configured so that
    endpoints can return a clear "not configured" error.
    """
    if not settings.garmin_email or not settings.garmin_password:
        return None
    return _real_client(
        settings.garmin_email,
        settings.garmin_password,
        settings.garmin_token_store,
    )


def garmin_client_or_raise(
    client: GarminClient | None = Depends(get_garmin_client),
) -> GarminClient:
    """Raise a clear error when Garmin credentials are missing."""
    if client is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Garmin credentials not configured. "
            "Set GARMIN_EMAIL and GARMIN_PASSWORD in the backend .env file.",
        )
    return client
