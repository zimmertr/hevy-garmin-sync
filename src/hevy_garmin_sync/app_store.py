"""The newest Hevy app on Apple's App Store, to say when Trainer's rules may be behind it (spec F-48a).

The rules match one Hevy app version (trainer_rules.HEVY_COMPATIBILITY), and
any newer release can change them. Nothing tells the app which version the
user's phone runs, so the newest one Apple lists stands in for it. iOS and
Android carry the same version numbers (2026-11-25).

One public lookup, no account or token. A failed one is only a missed check,
so it returns None and is not retried until the next day's.
"""

import logging

import requests

from .errors import ServiceError
from .hevy import TIMEOUT_SECONDS, USER_AGENT, get_json

LOOKUP = "https://itunes.apple.com/lookup?id=1458862350"  # Hevy - Workout Tracker Gym Log

log = logging.getLogger(__name__)


def newest_hevy(session: requests.Session | None = None) -> str | None:
    """The version Apple lists for Hevy, or None when the lookup fails or says nothing usable."""
    http = session or requests.Session()

    def send() -> requests.Response:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        return http.get(LOOKUP, headers=headers, timeout=TIMEOUT_SECONDS)

    try:
        reply = get_json(send, "App Store lookup")
    except ServiceError as e:
        log.debug("[App Store] %s failed: %s", e.request, e)
        return None
    results = reply.get("results") if isinstance(reply, dict) else None
    first = results[0] if isinstance(results, list) and results else None
    version = first.get("version") if isinstance(first, dict) else None
    return version if isinstance(version, str) and _parts(version) else None


def _parts(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def newer(version: str, than: str) -> bool:
    """`version` is a later release than `than`: 3.2.8.1 is after 3.2.8, and 3.2.10 after 3.2.9."""
    a, b = _parts(version), _parts(than)
    return a is not None and b is not None and a > b
