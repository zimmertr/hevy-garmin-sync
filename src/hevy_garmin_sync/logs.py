"""Logging: the app's only signal (spec O-2, O-3)."""

import json
import logging
import sys
from datetime import datetime
from typing import TextIO


def _timestamp(record: logging.LogRecord) -> str:
    """ISO 8601 with the offset, in the process's zone (which follows TZ)."""
    return datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds")


class _Text(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = f"{_timestamp(record)} {record.levelname} {record.name} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class _Json(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup(level: str, log_format: str, stream: TextIO | None = None, buffer: logging.Handler | None = None) -> None:
    """Log to `stream`, and to `buffer` too when given: the status page's copy of the last lines (W-6)."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(_Json() if log_format == "json" else _Text())
    root = logging.getLogger()
    root.handlers[:] = [handler, *([buffer] if buffer else [])]
    root.setLevel(level)
    # python-garminconnect logs every failed call with a traceback. The app
    # logs each failure once, with the fix, so the library only speaks at DEBUG.
    logging.getLogger("garminconnect").setLevel(logging.DEBUG if level == "DEBUG" else logging.CRITICAL)
    # urllib3's DEBUG lines carry whole URLs, and one Garmin URL holds the
    # account's display name (A-6).
    logging.getLogger("urllib3").setLevel(logging.WARNING)
