"""The last lines of the log, kept in memory for the status page (spec W-6).

The full log goes to stderr, where Docker and Kubernetes keep it; the app
writes no log file. A restart starts the buffer empty.
"""

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any

KEPT = 5000
PAGE = 200


class LogBuffer(logging.Handler):
    """Each record as time, level and message, numbered so the page can ask for the lines before one."""

    def __init__(self, kept: int = KEPT) -> None:
        super().__init__()
        self._lines: deque[dict[str, Any]] = deque(maxlen=kept)
        self._next = 1
        self._guard = threading.Lock()  # the loop appends while the server's thread reads

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        with self._guard:
            self._lines.append(
                {
                    "seq": self._next,
                    "time": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds"),
                    "level": record.levelname,
                    "message": message,
                }
            )
            self._next += 1

    def page(self, before: int | None = None, size: int = PAGE) -> dict[str, Any]:
        """Up to `size` lines older than `before` (the newest when None), oldest first, and whether more are kept."""
        with self._guard:
            older = [line for line in self._lines if before is None or line["seq"] < before]
        lines = older[-size:]
        return {"lines": lines, "more": len(older) > len(lines)}
