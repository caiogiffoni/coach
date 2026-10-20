"""Structured JSON logging built on the stdlib only.

Modules log as usual and attach context through ``extra``::

    logger = logging.getLogger(__name__)
    logger.info("week generated", extra={"week_start": "2026-10-19"})

Every ``extra`` key becomes a top-level field of the emitted JSON object.
"""

import json
import logging
import sys
from datetime import datetime, timezone

# Attributes every LogRecord carries; anything else on a record came from `extra`.
_RESERVED_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
) | {"message", "asctime", "taskName"}

_HANDLER_NAME = "coach-json"


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON line, merging ``extra`` fields in.

    Example:
        >>> handler.setFormatter(JsonFormatter())
    """

    def format(self, record: logging.LogRecord) -> str:
        """Serialize ``record`` to a single-line JSON string."""
        payload = self._base_fields(record)
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)

    def _base_fields(self, record: logging.LogRecord) -> dict[str, object]:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }


def _extra_fields(record: logging.LogRecord) -> dict[str, object]:
    """Return the attributes a caller attached to ``record`` via ``extra``."""
    return {
        key: value
        for key, value in vars(record).items()
        if key not in _RESERVED_RECORD_ATTRS
    }


def configure_logging(level: str = "INFO") -> None:
    """Install a single JSON stdout handler on the root logger (idempotent).

    Example:
        >>> configure_logging("DEBUG")
    """
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != _HANDLER_NAME]
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
