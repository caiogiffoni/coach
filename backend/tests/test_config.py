"""SECRET_KEY guard on Settings."""

import logging

import pytest
from pydantic import ValidationError

from app.config import DEV_SECRET_KEY, MIN_SECRET_KEY_BYTES, Settings


def make_settings(secret_key: str) -> Settings:
    # _env_file=None keeps a developer's backend/.env out of the test.
    return Settings(_env_file=None, secret_key=secret_key)  # type: ignore[call-arg]


def test_short_secret_key_is_rejected_with_length_in_message():
    with pytest.raises(ValidationError) as excinfo:
        make_settings("x" * (MIN_SECRET_KEY_BYTES - 1))
    message = str(excinfo.value)
    assert f"{MIN_SECRET_KEY_BYTES - 1} bytes" in message
    assert f">= {MIN_SECRET_KEY_BYTES} bytes" in message


def test_secret_key_length_counts_bytes_not_characters():
    # 11 three-byte characters = 33 bytes even though len() == 11.
    assert make_settings("€" * 11).secret_key == "€" * 11


def test_strong_secret_key_is_accepted_silently(caplog):
    with caplog.at_level(logging.WARNING, logger="app.config"):
        make_settings("k" * MIN_SECRET_KEY_BYTES)
    assert caplog.records == []


def test_dev_default_secret_key_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.config"):
        make_settings(DEV_SECRET_KEY)
    assert any("dev default" in r.getMessage() for r in caplog.records)
