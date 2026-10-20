"""JSON log formatter and root-logger configuration."""

import json
import logging
import sys

from app.logging_config import JsonFormatter, configure_logging


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.__dict__.update(extra)
    return record


def test_formatter_emits_base_fields_as_json():
    payload = json.loads(JsonFormatter().format(make_record()))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["timestamp"].endswith("+00:00")


def test_formatter_includes_extra_fields_and_skips_record_internals():
    payload = json.loads(JsonFormatter().format(make_record(week_start="2026-10-19")))
    assert payload["week_start"] == "2026-10-19"
    assert "args" not in payload and "lineno" not in payload


def test_formatter_stringifies_non_json_values():
    payload = json.loads(JsonFormatter().format(make_record(path=sys)))
    assert payload["path"].startswith("<module 'sys'")


def test_formatter_includes_exception_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        record = make_record()
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc_info"]


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    original_handlers, original_level = list(root.handlers), root.level
    try:
        configure_logging("debug")
        configure_logging("debug")
        json_handlers = [
            h for h in root.handlers if isinstance(h.formatter, JsonFormatter)
        ]
        assert len(json_handlers) == 1
        assert root.level == logging.DEBUG
    finally:
        root.handlers, root.level = original_handlers, original_level
