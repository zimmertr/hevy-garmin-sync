"""Garmin Connect, through python-garminconnect (spec A-2a).

Everything the app asks of Garmin goes through `Garmin` here, which adds what
the library leaves to its caller: one error vocabulary (errors.py), a pause
between writes (O-1b), and a durable copy of the token whenever Garmin rotates
it (A-4, O-3a). The library's own retries are off (O-1); its calls time out
after 15 seconds, and its token calls after 30 (O-1a).
"""

import base64
import binascii
import json
import logging
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import garminconnect
import requests

from .errors import (
    ConfigError,
    NotFound,
    RateLimited,
    Refused,
    Rejected,
    ServiceError,
    Stopped,
    Unavailable,
    retry_after,
)
from .store import Store

log = logging.getLogger(__name__)

TOKENS = "garmin_tokens.json"
LOGIN_FIX = "run `login` again and set GARMIN_TOKEN to the value it prints"
_PAGE = 100  # the most get_workouts returns per call (F-12)
_WRITE_GAP_SECONDS = 1.0  # O-1b


def encode_token(tokens_json: str) -> str:
    """The library's token JSON as one shell-safe line, the value of GARMIN_TOKEN (A-2)."""
    return base64.b64encode(tokens_json.encode("utf-8")).decode("ascii")


def decode_token(value: str) -> str:
    try:
        tokens_json = base64.b64decode(value.strip(), validate=True).decode("utf-8")
        tokens = json.loads(tokens_json)
    except (binascii.Error, ValueError) as e:
        raise ConfigError(f"GARMIN_TOKEN is not a value `login` printed; {LOGIN_FIX}") from e
    if not isinstance(tokens, dict) or not tokens.get("di_token"):
        raise ConfigError(f"GARMIN_TOKEN is not a value `login` printed; {LOGIN_FIX}")
    return tokens_json


class Garmin:
    def __init__(
        self,
        api: garminconnect.Garmin,
        store: Store,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        stopping: Callable[[], bool] = lambda: False,
    ) -> None:
        self._api = api
        self._store = store
        self._stopping = stopping
        self._sleep = sleep
        self._clock = clock
        self._saved = api.client.dumps()
        self._last_write = float("-inf")

    @classmethod
    def open(cls, env_token: str | None, store: Store, stopping: Callable[[], bool] = lambda: False) -> Garmin:
        """Load the token: the stored copy, unless GARMIN_TOKEN is new (A-4). No network."""
        if env_token and (store.read(TOKENS) is None or not store.seeded_by(TOKENS, env_token)):
            store.write(TOKENS, decode_token(env_token))
            store.mark_seed(TOKENS, env_token)
        elif store.read(TOKENS) is None:
            raise ConfigError(f"GARMIN_TOKEN is not set and DATA_DIR holds no Garmin token; {LOGIN_FIX}")
        api = garminconnect.Garmin(retry_attempts=0)
        try:
            # Loading from the file also tells the library where the token
            # lives, so it rewrites the file the moment Garmin rotates it.
            api.client.load(str(store.path(TOKENS)))
        except garminconnect.GarminConnectConnectionError as e:
            raise ConfigError(f"the Garmin token in DATA_DIR can't be read; {LOGIN_FIX}") from e
        return cls(api, store, stopping=stopping)

    def measurement_system(self) -> str | None:
        """`statute_us`, `metric` or `statute_uk`. Also the cheapest call that proves the token works."""
        settings = self._call(self._api.get_user_profile)
        system = (settings.get("userData") or {}).get("measurementSystem")
        return system if isinstance(system, str) else None

    def time_zone(self) -> str | None:
        """The profile's IANA time zone, or None when Garmin doesn't give one (C-7)."""

        def read() -> str | None:
            profile = self._api.connectapi("/userprofile-service/socialProfile")
            self._api.display_name = profile.get("displayName")
            return self._api.get_user_timezone()

        try:
            return self._call(read)
        except ServiceError:
            return None

    def workouts(self) -> list[dict[str, Any]]:
        """Every workout in the account, with its description (U-26)."""
        found: list[dict[str, Any]] = []
        while True:
            page = self._call(lambda: self._api.get_workouts(len(found), _PAGE))
            found.extend(page)
            if len(page) < _PAGE:
                return found

    def create(self, body: dict[str, Any]) -> int:
        return int(self._call(lambda: self._api.upload_workout(body), write=True)["workoutId"])

    def update(self, workout_id: int, body: dict[str, Any]) -> None:
        """Replace the workout in place: it keeps its id, so calendar entries stay valid (F-13)."""
        self._call(lambda: self._api.update_workout(workout_id, body), write=True)

    def delete(self, workout_id: int) -> None:
        try:
            self._call(lambda: self._api.delete_workout(workout_id), write=True)
        except NotFound:
            pass  # already gone, which is what was asked for

    def send_to_device(self, workout_id: int) -> None:
        """Queue the workout for the device that synced last (F-31a)."""
        self._call(lambda: self._api.push_workout_to_device(workout_id), write=True)

    def scheduled(self, start: date, end: date) -> list[dict[str, Any]]:
        """The calendar's workout entries between two days, everyone's, not only the app's."""
        return self._call(lambda: self._api.get_scheduled_workouts_by_period(start.isoformat(), end.isoformat()))

    def schedule(self, workout_id: int, day: date) -> int | None:
        """Put the workout on a day's calendar. Returns the entry's id, which removing it needs."""
        entry = self._call(lambda: self._api.schedule_workout(workout_id, day.isoformat()), write=True)
        entry_id = entry.get("workoutScheduleId") if isinstance(entry, dict) else None
        return int(entry_id) if entry_id is not None else None

    def unschedule(self, entry_id: int) -> None:
        try:
            self._call(lambda: self._api.unschedule_workout(entry_id), write=True)
        except NotFound:
            pass

    def _call[T](self, request: Callable[[], T], *, write: bool = False) -> T:
        if write:
            if self._stopping():
                raise Stopped
            wait = self._last_write + _WRITE_GAP_SECONDS - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            return request()
        except garminconnect.GarminConnectTooManyRequestsError as e:
            # The library raises a read's 429 from its own error that holds the reply. A 429 on its
            # token exchange holds none, so the app's own wait applies (O-1, #27).
            raise RateLimited(str(e), retry_after(getattr(e.__cause__, "response", None))) from e
        except garminconnect.GarminConnectAuthenticationError as e:
            raise Rejected(str(e)) from e
        except garminconnect.GarminConnectConnectionError as e:
            error = _by_status(getattr(e.response, "status_code", None), str(e))
            if isinstance(error, RateLimited):
                error.retry_after = retry_after(e.response)  # a write's 429 comes untranslated, reply attached
            raise error from e
        except requests.RequestException as e:
            # Writes reach `requests` without the library's translation.
            raise Unavailable(type(e).__name__) from e
        except (KeyError, TypeError, ValueError) as e:
            # A reply in a shape the library didn't expect, such as no device to send to.
            raise Refused(f"unexpected reply from Garmin ({type(e).__name__}: {e})") from e
        finally:
            if write:
                self._last_write = self._clock()
            self._keep_token()

    def _keep_token(self) -> None:
        """Save the token when Garmin rotated it during the call.

        Garmin kills the old refresh token on every refresh. The library
        already rewrote the file, but without flushing it to disk and without
        reporting a failure, so write it again here, durably and loudly.
        """
        current = self._api.client.dumps()
        if current == self._saved:
            return
        try:
            self._store.write(TOKENS, current)
        except OSError as e:
            log.error("Could not save the refreshed Garmin token to DATA_DIR (%s). After a restart, %s.", e, LOGIN_FIX)
            return
        self._saved = current


def _by_status(status: int | None, message: str) -> ServiceError:
    if status in (401, 403):
        return Rejected(message)
    if status == 429:
        return RateLimited(message)
    if status == 404:
        return NotFound(message)
    if status is not None and 400 <= status < 500:
        return Refused(message)
    return Unavailable(message)
