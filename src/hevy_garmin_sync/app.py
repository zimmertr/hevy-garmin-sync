"""The process: check the configuration, sync everything, then poll Hevy and roll over at midnight (spec F-1).

One thread and no ports. Every timer lives in the loop here: the poll
interval, local midnight, the waits after a failure, and the hourly line that
says the app is alive.
"""

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from typing import TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__, logs
from . import config as configuration
from .config import Config
from .errors import ConfigError, RateLimited, Refused, Rejected, ServiceError, Stopped
from .exercises import ExerciseMap
from .garmin import LOGIN_FIX, Garmin
from .hevy import API_KEY_FIX, Hevy
from .routines import Routines
from .store import Store
from .sync import Plans, Sync
from .workout import TRAINER

log = logging.getLogger(__name__)

_QUIET_NOTE_SECONDS = 3600  # O-3


class Backoff:
    """How long to leave one service alone after it fails (O-1).

    One minute, doubling, at most thirty; a rate limit starts at
    `rate_limited` seconds. Each service has its own, so Hevy is still polled
    while Garmin is down.
    """

    FIRST = 60.0
    LIMIT = 1800.0

    def __init__(self, clock: Callable[[], float], rate_limited: float = FIRST) -> None:
        self._clock = clock
        self._rate_limited = rate_limited
        self._delay = 0.0
        self._until = float("-inf")

    def ready(self) -> bool:
        return self._clock() >= self._until

    def failed(self, error: BaseException) -> float:
        delay = self._delay * 2 or self.FIRST
        if isinstance(error, RateLimited):
            delay = max(delay, self._rate_limited)
        self._delay = min(delay, self.LIMIT)
        self._until = self._clock() + self._delay
        return self._delay

    def succeeded(self) -> None:
        self._delay = 0.0
        self._until = float("-inf")


def _problem(service: str, fix: str, error: ServiceError) -> str:
    """What failed and how to fix it, for the log (O-1)."""
    if isinstance(error, Rejected):
        return f"{service} rejected the app's credentials; {fix}"
    if isinstance(error, RateLimited):
        return f"{service} is rate limiting the app; nothing to do but wait"
    if isinstance(error, Refused):
        return f"{service} refused a request ({error})"
    return f"{service} can't be reached or is failing ({error}); it will recover by itself when {service} does"


class App:
    def __init__(
        self,
        config: Config,
        hevy: Hevy,
        garmin: Garmin,
        exercises: ExerciseMap,
        *,
        wait: Callable[[float], bool],
        clock: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._hevy = hevy
        self._garmin = garmin
        self._wait = wait  # sleeps, and returns True when the app was told to stop
        self._clock = clock
        self._utcnow = utcnow
        self._zone: ZoneInfo = config.zone or ZoneInfo("UTC")
        self._routines = Routines(hevy, config.include_folders, exercises)
        self._sync = Sync(garmin, config.scheduled, self._now)
        self._hevy_backoff = Backoff(clock)
        self._garmin_backoff = Backoff(clock, rate_limited=900.0)
        self._plans: list[Plans] | None = None

    def _now(self) -> datetime:
        return self._utcnow().astimezone(self._zone)

    def run(self) -> int:
        try:
            self._start()
            self._loop()
        except ConfigError as e:
            log.error("%s", e)
            return 1
        except Stopped:
            pass
        log.info("Stopped")
        return 0

    def _start(self) -> None:
        """One call to each service: a rejected credential exits here, with the fix (section 11)."""
        self._until_ok("Hevy", API_KEY_FIX, self._hevy_backoff, self._routines.check)
        self._until_ok("Garmin", LOGIN_FIX, self._garmin_backoff, self._garmin.measurement_system)
        self._choose_zone()

    def _until_ok(self, service: str, fix: str, backoff: Backoff, call: Callable[[], object]) -> None:
        while True:
            try:
                call()
                backoff.succeeded()
                return
            except Rejected as e:
                raise ConfigError(_problem(service, fix, e)) from e
            except ServiceError as e:
                delay = backoff.failed(e)
                log.error("%s. Trying again in %d min.", _problem(service, fix, e), delay / 60)
                if self._wait(delay):
                    raise Stopped from None

    def _choose_zone(self) -> None:
        """TZ, else the Garmin profile's zone, else UTC with a warning (C-7)."""
        if self._config.zone:
            log.info("Time zone: %s (from TZ)", self._zone.key)
            return
        name = self._garmin.time_zone()
        try:
            self._zone = ZoneInfo(name or "")
            log.info("Time zone: %s (from the Garmin profile; set TZ to override)", self._zone.key)
        except ZoneInfoNotFoundError, ValueError, OSError:
            log.warning("Time zone: UTC, because TZ is unset and the Garmin profile gave none. Set TZ.")

    def _loop(self) -> None:
        day = None
        full = True
        quiet_since = self._clock()
        quiet_polls = 0
        while True:
            now = self._now()
            if now.date() != day:
                full = True  # the first run, and every local midnight (F-31)
            changed = False
            plans = self._read_hevy()
            if plans is None and full:
                # Hevy is down, but the calendar still rolls over on what Hevy said last.
                plans = self._plans
            if plans is not None and self._garmin_backoff.ready():
                try:
                    counts = self._sync.run(plans, full)
                except ServiceError as e:
                    full = True  # whatever was half done is finished by a full run (O-1, O-3a)
                    delay = self._garmin_backoff.failed(e)
                    log.error("%s. Trying again in %d min.", _problem("Garmin", LOGIN_FIX, e), delay / 60)
                except Stopped:
                    raise
                except Exception as e:  # noqa: BLE001 a bug must not become a restart loop that hammers Garmin
                    full = True
                    delay = self._garmin_backoff.failed(e)
                    log.exception("Unexpected error while syncing. Trying again in %d min.", delay / 60)
                else:
                    self._garmin_backoff.succeeded()
                    if full or counts.any():
                        log.info("Sync: %s", counts)
                    changed = counts.any()
                    if full:
                        day, full = now.date(), False
            if changed:
                quiet_since, quiet_polls = self._clock(), 0
            else:
                quiet_polls += 1
                if self._clock() - quiet_since >= _QUIET_NOTE_SECONDS:
                    log.info("Nothing changed in the last hour (%d polls)", quiet_polls)
                    quiet_since, quiet_polls = self._clock(), 0
            # A second past midnight, so the wake-up is surely on the new day.
            if self._wait(min(self._config.poll_seconds, self._seconds_to_midnight() + 1)):
                raise Stopped

    def _read_hevy(self) -> list[Plans] | None:
        """What Hevy wants in Garmin now, or None while Hevy is failing."""
        if not self._hevy_backoff.ready():
            return None
        calls = self._hevy.calls
        try:
            # With no Hevy Trainer source, the Trainer workouts the app owns are not wanted (section 6).
            plans = [self._routines.plans(), Plans(TRAINER, ())]
        except ServiceError as e:
            delay = self._hevy_backoff.failed(e)
            log.error("%s. Trying again in %d min.", _problem("Hevy", API_KEY_FIX, e), delay / 60)
            return None
        except Exception as e:  # noqa: BLE001 a reply in a shape the app didn't expect must not end the process
            delay = self._hevy_backoff.failed(e)
            log.exception("Unexpected error while reading Hevy. Trying again in %d min.", delay / 60)
            return None
        self._hevy_backoff.succeeded()
        log.debug("Hevy poll: %d calls, %d routines", self._hevy.calls - calls, len(plans[0].workouts))
        self._plans = plans
        return plans

    def _seconds_to_midnight(self) -> float:
        now = self._now()
        midnight = datetime.combine(now.date() + timedelta(days=1), clock_time.min, tzinfo=self._zone)
        # Through UTC: two times in one zone subtract by the wall clock, which is wrong across a clock change.
        return (midnight.astimezone(UTC) - now.astimezone(UTC)).total_seconds()


def main(env: Mapping[str, str] = os.environ, err: TextIO = sys.stderr) -> int:
    try:
        config = configuration.load(env)
    except ConfigError as e:
        print(f"hevy-garmin-sync: {e}", file=err)
        return 1
    logs.setup(config.log_level, config.log_format, err)
    log.info("hevy-garmin-sync %s", __version__)
    for name, value in config.summary().items():
        log.info("%s: %s", name, value)

    # SIGTERM and SIGINT only set a flag: the write in progress finishes, no new one starts (O-3a).
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    try:
        garmin = Garmin.open(config.garmin_token, Store(config.data_dir), stopping=stop.is_set)
    except ConfigError as e:
        log.error("%s", e)
        return 1
    return App(config, Hevy(config.hevy_api_key), garmin, ExerciseMap.load(), wait=stop.wait).run()
