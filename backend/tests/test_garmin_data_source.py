"""Which Garmin client sync reads from, decided by GARMIN_API_KEY."""

import pytest

from app.config import settings
from app.garmin.data_source import get_personal_api_client
from app.garmin.personal_api import PersonalApiGarminClient


def test_no_api_key_means_no_personal_client(monkeypatch):
    monkeypatch.setattr(settings, "garmin_api_key", "")

    assert get_personal_api_client() is None


def test_api_key_gives_one_cached_personal_client(monkeypatch):
    monkeypatch.setattr(settings, "garmin_api_key", "key-from-env")

    first = get_personal_api_client()

    assert isinstance(first, PersonalApiGarminClient)
    assert get_personal_api_client() is first  # token cache survives requests


@pytest.fixture(autouse=True)
def _reset_client_cache():
    from app.garmin.data_source import _personal_client

    _personal_client.cache_clear()
    yield
    _personal_client.cache_clear()
