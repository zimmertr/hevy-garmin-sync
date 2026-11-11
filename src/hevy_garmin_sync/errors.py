"""The failures the app tells apart. Hevy and Garmin fail in the same four ways (spec O-1, F-16)."""

import email.utils
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


class ConfigError(Exception):
    """Bad or missing configuration, or a credential a service rejected: the app exits 1, naming the fix (O-1)."""


class Stopped(Exception):
    """The app was told to stop, so no new write to Garmin starts (spec O-3a)."""


class ServiceError(Exception):
    """A call to Hevy or Garmin failed."""


class Rejected(ServiceError):
    """The service refused the credentials (401, 403). Fixed by the user, not by waiting, so the app exits (O-1)."""


class RateLimited(ServiceError):
    """The service said to slow down (429). `retry_after` is the wait it asked for, in seconds, when it said (O-1)."""

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Unavailable(ServiceError):
    """Unreachable, timed out, or a server error. Worth retrying."""


class Refused(ServiceError):
    """The service refused this one request (another 4xx). Retrying the same request won't help."""


class NotFound(Refused):
    """What the request named does not exist (404)."""


def retry_after(reply: Any, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> float | None:
    """The seconds a 429 reply's `Retry-After` asks the app to wait, or None when it gives none the app can read.

    The header is a whole number of seconds or an HTTP date (RFC 9110). A value
    that is neither is ignored, so the app's own wait applies (O-1, #27).
    """
    value = (getattr(reply, "headers", None) or {}).get("Retry-After")
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)  # a "-0000" zone parses as naive; an HTTP date is always UTC
    return max(0.0, (when - now()).total_seconds())
