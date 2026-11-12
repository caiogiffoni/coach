"""FastAPI dependencies choosing where sync reads Garmin data from.

One decision lives here: a configured ``GARMIN_API_KEY`` (Personal API) wins
over the email/password login, which stays the only way to push workouts.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from ..config import settings
from .client import (
    GarminClient,
    GarminDataSource,
    get_garmin_client,
    require_garmin_configured,
)
from .personal_api import PersonalApiGarminClient, UrllibPersonalApiTransport


@lru_cache(maxsize=1)
def _personal_client(api_key: str) -> PersonalApiGarminClient:
    # Cached so the 24 h bearer token is reused across requests.
    return PersonalApiGarminClient(api_key, UrllibPersonalApiTransport())


def get_personal_api_client() -> GarminDataSource | None:
    """FastAPI dependency: the API-key client, or None when no key is set."""
    if not settings.garmin_api_key:
        return None
    return _personal_client(settings.garmin_api_key)


def get_garmin_data_source(
    personal: GarminDataSource | None = Depends(get_personal_api_client),
    password_client: GarminClient | None = Depends(get_garmin_client),
) -> GarminDataSource | None:
    """Prefer the Personal API key; fall back to the password-login client.

    Example:
        ``Depends(get_garmin_data_source)`` in a router signature.
    """
    return personal or password_client


def garmin_data_source_or_raise(
    source: GarminDataSource | None = Depends(get_garmin_data_source),
) -> GarminDataSource:
    """Raise a clear 403 when neither an API key nor credentials are set."""
    return require_garmin_configured(
        source,
        "Garmin not configured. Set GARMIN_API_KEY (Personal API key) or "
        "GARMIN_EMAIL and GARMIN_PASSWORD in the backend .env file.",
    )
