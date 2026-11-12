"""The process: check the configuration, sync everything, then poll Hevy and roll over at midnight (spec F-1).

One loop does every Hevy and Garmin call. Every timer lives in it: the poll
interval, local midnight, the waits after a failure, and the hourly line that
says the app is alive. A second thread serves the status page (server.py); it
only reads the status the loop publishes and asks for a manual sync (W-1).
"""

import logging
import math
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from typing import Any, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__, logs, server, status
from . import config as configuration
from .config import Config
from .errors import ConfigError, RateLimited, Refused, Rejected, ServiceError, Stopped
from .exercises import ExerciseMap
from .garmin import LOGIN_FIX, Garmin
from .hevy import KEY_FIX, Hevy
from .hevy_private import SESSION, SESSION_FIX, HevyPrivate
from .logbuffer import LogBuffer
from .previous import Previous
from .routines import Routines
from .store import Store
from .sync import Counts, Plans, Sync
from .trainer import Trainer
from .workout import TRAINER

log = logging.getLogger(__name__)

_QUIET_NOTE_SECONDS = 3600  # O-3
# How long one pass may take before /healthz says the loop is stuck: a full run
# writes one workout a second at most (O-1b), and each call can wait on a timeout.
_PASS_SECONDS = 900.0
_MARGIN_SECONDS = 120.0  # on top of a wait, before the wait counts as stuck (W-7)

HEVY, TRAINER_SERVICE, GARMIN = "Hevy", "Hevy Trainer", "Garmin"


class Backoff:
    """How long to leave one service alone after it fails (O-1).

    One minute, doubling, at most thirty; a rate limit starts at
    `rate_limited` seconds. A rate limit that says how long to wait is waited
    that long instead, even past thirty minutes, but never less than
    `shortest` (TJ, 2026-11-10, #27). Each service has its own, so Hevy is
    still polled while Garmin is down.
    """

    FIRST = 60.0
    LIMIT = 1800.0

    def __init__(self, clock: Callable[[], float], rate_limited: float = FIRST, shortest: float = FIRST) -> None:
        self._clock = clock
        self._rate_limited = rate_limited
        self._shortest = shortest  # the poll interval, so a `Retry-After: 0` can't become a burst of calls
        self._delay = 0.0
        self._until = float("-inf")
        self.reason = ""  # what failed last, for the status page (W-2)

    def ready(self) -> bool:
        return self._clock() >= self._until

    def remaining(self) -> float:
        """Seconds until the wait ends; 0 when there is none."""
        return max(self._until - self._clock(), 0.0)

    def failed(self, error: BaseException, reason: str = "") -> float:
        delay = self._delay * 2 or self.FIRST
        if isinstance(error, RateLimited):
            delay = max(delay, self._rate_limited)
        self._delay = min(delay, self.LIMIT)
        wait = self._delay
        if isinstance(error, RateLimited) and error.retry_after is not None:
            wait = max(error.retry_after, self._shortest)
        self._until = self._clock() + wait
        self.reason = reason
        return wait

    def succeeded(self) -> None:
        self._delay = 0.0
        self._until = float("-inf")
        self.reason = ""


class Requests:
    """Manual syncs from the page, the API and the `sync` command: one door, one limit (W-3).

    A request while one is waiting or running joins it. One within `GAP`
    seconds of the last manual sync's end is refused with the seconds left.
    The time lives in memory, so a restart clears it; a restart syncs anyway.
    """

    GAP = 60.0

    def __init__(self, clock: Callable[[], float], nudge: Callable[[], None]) -> None:
        self._clock = clock
        self._nudge = nudge  # wakes the loop from its wait
        self._guard = threading.Lock()
        self._pending = False
        self._fresh = False  # asked for since the loop last looked
        self._running = False
        self.force = False
        self._ended = float("-inf")

    def ask(self, force: bool) -> tuple[str, int]:
        """`started`, `joined`, or `wait` with the whole seconds left."""
        with self._guard:
            if self._pending or self._running:
                if self._pending and not self._running:
                    self.force = self.force or force  # a Force pressed before the sync starts still counts
                return "joined", 0
            left = self.GAP - (self._clock() - self._ended)
            if left > 0:
                return "wait", math.ceil(left)
            self._pending, self._fresh, self.force = True, True, force
        self._nudge()
        return "started", 0

    def pending(self) -> bool:
        with self._guard:
            return self._pending

    def fresh(self) -> bool:
        """True once per request: the first pass that sees it."""
        with self._guard:
            fresh, self._fresh = self._fresh, False
            return fresh

    def begin(self) -> None:
        with self._guard:
            self._pending, self._running = False, True

    def end(self) -> None:
        with self._guard:
            self._running, self.force = False, False
            self._ended = self._clock()


def _for(seconds: float) -> str:
    """A wait for the log: whole minutes, or seconds under one, so a short wait never reads as 0 min."""
    return f"{seconds / 60:.0f} min" if seconds >= 60 else f"{seconds:.0f} s"


def _problem(service: str, fix: str, error: ServiceError) -> str:
    """What failed and how to fix it, for the log (O-1)."""
    if isinstance(error, Rejected):
        return f"{service} rejected the app's credentials; {fix}"
    if isinstance(error, RateLimited) and error.retry_after is not None:
        return f"{service} is rate limiting the app and said how long to wait; nothing to do but wait"
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
        hevy_private: HevyPrivate | None = None,  # None: HEVY_SESSION is unset, so Hevy Trainer is off
        wait: Callable[[float], bool],
        nudge: Callable[[], None] = lambda: None,  # ends the current wait early, for a manual sync
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
        self._previous = Previous(hevy, self._now) if config.previous_values else None
        self._routines = Routines(hevy, config.include_folders, exercises, self._previous)
        self._trainer = Trainer(hevy_private, hevy, exercises, self._now, self._previous) if hevy_private else None
        self._events_since = self._now()  # workouts logged before startup are in the first reads (F-4)
        self._sync = Sync(garmin, config.scheduled, self._now)
        self._hevy_backoff = Backoff(clock, shortest=config.poll_seconds)
        self._trainer_backoff = Backoff(clock, shortest=config.poll_seconds)
        self._garmin_backoff = Backoff(clock, rate_limited=900.0, shortest=config.poll_seconds)
        self._plans: list[Plans] | None = None
        # Until Hevy Trainer has answered once, its workouts in Garmin are left as they are.
        self._trainer_plans = Plans(TRAINER, (), hold=True)
        self.requests = Requests(clock, nudge)
        # A rejected credential stops its service until the fix and a restart (W-8): service -> the fix.
        self._rejected: dict[str, str] = {}
        self._started = self._now()
        self._run = status.Run()
        self._last_daily: tuple[datetime, Counts] | None = None
        self._last_manual: tuple[datetime, Counts | None] | None = None  # None counts: it failed
        self._next_auto: datetime | None = None
        self._deadline = clock() + _PASS_SECONDS
        self.status: dict[str, Any] = {}
        self._publish()

    def _now(self) -> datetime:
        return self._utcnow().astimezone(self._zone)

    def alive(self) -> bool:
        """The loop is passing or waiting as planned (W-7). A wait after a failure counts as alive."""
        return self._clock() < self._deadline

    def ready(self) -> bool:
        """No sign-in is rejected (W-8)."""
        return not self._rejected

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

    def _sleep(self, seconds: float) -> bool:
        """Wait, noting when the loop should be back for /healthz. True when the app was told to stop."""
        self._deadline = self._clock() + seconds + _MARGIN_SECONDS
        stopped = self._wait(seconds)
        self._deadline = self._clock() + _PASS_SECONDS
        return stopped

    def _start(self) -> None:
        """One call to each service, so a rejected credential shows at once with the fix (section 11)."""
        self._until_ok(HEVY, KEY_FIX, self._hevy_backoff, self._routines.check)
        if self._trainer:
            self._until_ok(TRAINER_SERVICE, SESSION_FIX, self._trainer_backoff, self._trainer.check)
        self._until_ok(GARMIN, LOGIN_FIX, self._garmin_backoff, self._garmin.measurement_system)
        self._choose_zone()

    def _until_ok(self, service: str, fix: str, backoff: Backoff, call: Callable[[], object]) -> None:
        while True:
            try:
                call()
                backoff.succeeded()
                return
            except Rejected as e:
                self._reject(service, fix, e)
                return
            except ServiceError as e:
                delay = backoff.failed(e, _problem(service, fix, e))
                log.error("%s. Trying again in %s.", backoff.reason, _for(delay))
                self._publish()
                # A manual sync ends a wait early, but never a service's wait (W-3).
                while not backoff.ready():
                    if self._sleep(backoff.remaining()):
                        raise Stopped from None

    def _reject(self, service: str, fix: str, error: Rejected) -> None:
        """Stop calling a service whose credential was refused: waiting can't fix it (O-1, W-8).

        The rest keeps running. A rejected HEVY_SESSION stops only Hevy Trainer,
        and its Garmin workouts stay as they are.
        """
        if service not in self._rejected:
            log.error("%s. Until then the app leaves %s alone.", _problem(service, fix, error), service)
        self._rejected[service] = fix
        self._publish()

    def _choose_zone(self) -> None:
        """TZ, else the Garmin profile's zone, else UTC with a warning (C-7)."""
        if self._config.zone:
            log.info("Time zone: %s (from TZ)", self._zone.key)
            return
        name = None if GARMIN in self._rejected else self._garmin.time_zone()
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
            self._deadline = self._clock() + _PASS_SECONDS
            now = self._now()
            if now.date() != day:
                full = True  # the first run, and every local midnight (F-31)
            manual = self.requests.pending()
            if manual:
                full = True
                if self.requests.fresh():
                    self._take_request()
            changed = False
            garmin_free = GARMIN not in self._rejected and self._garmin_backoff.ready()
            plans = self._read_hevy(manual and garmin_free)
            if plans is None and full:
                # Hevy is down, but the calendar still rolls over on what Hevy said last.
                plans = self._plans
            if manual and not garmin_free and GARMIN not in self._rejected:
                # Garmin's wait holds: the sync starts when it ends (W-3).
                self._run = status.Run("waiting", self.requests.force, starts=self._later(self._garmin_backoff))
            if plans is not None and garmin_free:
                force = manual and self.requests.force
                if manual:
                    self.requests.begin()
                    self._sync.resend_all()
                counts = None
                try:
                    counts = self._sync.run(plans, full, force, self._progress if manual else status_quiet)
                except Rejected as e:
                    # Garmin's last call has already returned, so no write is cut short (O-3a).
                    self._reject(GARMIN, LOGIN_FIX, e)
                except ServiceError as e:
                    full = True  # whatever was half done is finished by a full run (O-1, O-3a)
                    delay = self._garmin_backoff.failed(e, _problem(GARMIN, LOGIN_FIX, e))
                    log.error("%s. Trying again in %s.", self._garmin_backoff.reason, _for(delay))
                except Stopped:
                    raise
                except Exception as e:  # noqa: BLE001 a bug must not become a restart loop that hammers Garmin
                    full = True
                    delay = self._garmin_backoff.failed(e, "Unexpected error while syncing")
                    log.exception("Unexpected error while syncing. Trying again in %s.", _for(delay))
                else:
                    self._garmin_backoff.succeeded()
                    if full or counts.any():
                        log.info("Sync: %s", counts)
                    changed = counts.any()
                    if full:
                        if now.date() != day:
                            self._last_daily = (now, counts)
                        day, full = now.date(), False
                finally:
                    if manual:
                        self._last_manual = (self._now(), counts)
                        self.requests.end()
                        self._run = status.Run()
            elif manual and GARMIN in self._rejected:
                self.requests.begin()  # nothing to wait for: Garmin's sign-in needs fixing first
                self.requests.end()
                self._run = status.Run()
            if changed:
                quiet_since, quiet_polls = self._clock(), 0
            else:
                quiet_polls += 1
                if self._clock() - quiet_since >= _QUIET_NOTE_SECONDS:
                    log.info("Nothing changed in the last hour (%d polls)", quiet_polls)
                    quiet_since, quiet_polls = self._clock(), 0
            # A second past midnight, so the wake-up is surely on the new day.
            pause = min(self._config.poll_seconds, self._seconds_to_midnight() + 1)
            self._next_auto = self._now() + timedelta(seconds=pause)
            self._publish()
            if self._sleep(pause):
                raise Stopped

    def _take_request(self) -> None:
        """A new manual sync: Trainer reads its inputs again, and Force reads last time's sets again (W-3, W-4)."""
        force = self.requests.force
        log.info("Manual sync asked for%s", " (forced: every workout is rewritten)" if force else "")
        if self._trainer:
            self._trainer.logged()
        if force and self._previous:
            self._previous.forget()

    def _progress(self, step: str, done: int, total: int) -> None:
        self._run = status.Run("running", self.requests.force, step, done, total)
        self._publish()

    def _later(self, backoff: Backoff) -> datetime:
        return self._now() + timedelta(seconds=backoff.remaining())

    def _read_hevy(self, manual: bool = False) -> list[Plans] | None:
        """What Hevy wants in Garmin now, or None while Hevy is failing."""
        if HEVY in self._rejected or not self._hevy_backoff.ready():
            return None
        if manual:
            self._progress("Reading Hevy", 0, 0)
        calls = self._hevy.calls
        try:
            self._read_events()
            routines = self._routines.plans()
        except Rejected as e:
            self._reject(HEVY, KEY_FIX, e)
            return None
        except ServiceError as e:
            delay = self._hevy_backoff.failed(e, _problem(HEVY, KEY_FIX, e))
            log.error("%s. Trying again in %s.", self._hevy_backoff.reason, _for(delay))
            return None
        except Exception as e:  # noqa: BLE001 a reply in a shape the app didn't expect must not end the process
            delay = self._hevy_backoff.failed(e, "Unexpected error while reading Hevy")
            log.exception("Unexpected error while reading Hevy. Trying again in %s.", _for(delay))
            return None
        self._hevy_backoff.succeeded()
        log.debug("Hevy poll: %d calls, %d routines", self._hevy.calls - calls, len(routines.workouts))
        if manual and self._trainer:
            self._progress("Reading Hevy Trainer", 0, 0)
        self._plans = [routines, self._read_trainer()]
        return self._plans

    def _read_events(self) -> None:
        """The workouts saved, edited or deleted since the last read: one read a poll, for all who need it (F-4).

        Nobody needs them without Hevy Trainer or last time's sets, so then
        nothing is read. The cursor moves only once Hevy has answered.
        """
        if self._previous is None and self._trainer is None:
            return
        now = self._now()
        events = self._hevy.workout_events(self._events_since)
        self._events_since = now
        if not events:
            return
        # Trainer first: it only takes note, so a reply that last time's sets can't read still reaches it.
        if self._trainer:
            self._trainer.logged()
        if self._previous:
            self._previous.update(events)

    def _read_trainer(self) -> Plans:
        """What Hevy Trainer wants in Garmin now; what it wanted last while it is failing.

        Trainer has its own wait after a failure, so routines keep syncing
        when only Hevy's private API is down. A rejected session stops Trainer
        alone, and its Garmin workouts are kept as they are (W-8).
        """
        if self._trainer is None:
            # HEVY_SESSION is unset: the Trainer workouts the app owns are not wanted (section 6).
            return Plans(TRAINER, ())
        if TRAINER_SERVICE in self._rejected or not self._trainer_backoff.ready():
            return self._trainer_plans
        calls = self._hevy.calls + self._trainer.private_calls
        try:
            self._trainer_plans = self._trainer.plans()
        except Rejected as e:
            # HevyPrivate has already refreshed the session and tried once more, so it is dead (O-1).
            self._reject(TRAINER_SERVICE, SESSION_FIX, e)
            self._trainer_plans = replace(self._trainer_plans, hold=True)  # as it was, calendar and all
        except ServiceError as e:
            delay = self._trainer_backoff.failed(e, _problem(TRAINER_SERVICE, SESSION_FIX, e))
            log.error("%s. Trying again in %s.", self._trainer_backoff.reason, _for(delay))
        except Exception as e:  # noqa: BLE001 a reply in a shape the app didn't expect must not end the process
            delay = self._trainer_backoff.failed(e, "Unexpected error while reading Hevy Trainer")
            log.exception("Unexpected error while reading Hevy Trainer. Trying again in %s.", _for(delay))
        else:
            self._trainer_backoff.succeeded()
            log.debug(
                "Hevy Trainer poll: %d calls, %d workouts",
                self._hevy.calls + self._trainer.private_calls - calls,
                len(self._trainer_plans.workouts),
            )
        return self._trainer_plans

    def _seconds_to_midnight(self) -> float:
        now = self._now()
        midnight = datetime.combine(now.date() + timedelta(days=1), clock_time.min, tzinfo=self._zone)
        # Through UTC: two times in one zone subtract by the wall clock, which is wrong across a clock change.
        return (midnight.astimezone(UTC) - now.astimezone(UTC)).total_seconds()

    def _service(self, name: str, backoff: Backoff, on: bool = True) -> status.Service:
        if not on:
            return status.Service(name, "off", "Set HEVY_SESSION to sync Hevy Trainer's workouts.")
        if name in self._rejected:
            return status.Service(name, "rejected", self._rejected[name])
        if not backoff.ready():
            return status.Service(name, "waiting", backoff.reason, self._later(backoff))
        return status.Service(name, "working")

    def _publish(self) -> None:
        """Build the status the page reads, and swap it in whole (W-2)."""
        now = self._now()
        self.status = status.build(
            status.Facts(
                version=__version__,
                zone=self._zone.key,
                started=self._started,
                poll_seconds=self._config.poll_seconds,
                next_auto_sync=self._next_auto,
                last_daily_run=self._last_daily[0] if self._last_daily else None,
                last_counts=self._last_daily[1] if self._last_daily else None,
                next_daily_run=now + timedelta(seconds=self._seconds_to_midnight()),
                services=(
                    self._service(HEVY, self._hevy_backoff),
                    self._service(TRAINER_SERVICE, self._trainer_backoff, on=self._trainer is not None),
                    self._service(GARMIN, self._garmin_backoff),
                ),
                run=self._run,
                last_manual=self._last_manual[0] if self._last_manual else None,
                last_manual_counts=self._last_manual[1] if self._last_manual else None,
                reports=self._sync.report(),
                system=self._sync.system,
                settings=self._config.summary(),
            )
        )


def status_quiet(step: str, done: int, total: int) -> None:
    """An automatic pass reports no progress: only a manual sync shows its steps (W-3)."""


def main(env: Mapping[str, str] = os.environ, err: TextIO = sys.stderr) -> int:
    try:
        config = configuration.load(env)
    except ConfigError as e:
        print(f"hevy-garmin-sync: {e}", file=err)
        return 1
    buffer = LogBuffer()
    logs.setup(config.log_level, config.log_format, err, buffer)
    log.info("hevy-garmin-sync %s", __version__)
    for name, value in config.summary().items():
        log.info("%s: %s", name, value)

    # SIGTERM and SIGINT only set a flag: the write in progress finishes, no new one starts (O-3a).
    # `wake` ends a wait early, for a stop or a manual sync; `stop` says which.
    stop = threading.Event()
    wake = threading.Event()

    def halt(*_: object) -> None:
        stop.set()
        wake.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, halt)

    def wait(seconds: float) -> bool:
        wake.wait(seconds)
        wake.clear()
        return stop.is_set()

    store = Store(config.data_dir)
    try:
        garmin = Garmin.open(config.garmin_token, store, stopping=stop.is_set)
        hevy_private = HevyPrivate.open(config.hevy_session, store) if config.hevy_session else None
    except ConfigError as e:
        log.error("%s", e)
        return 1
    if hevy_private is None:
        # Only the variable turns Hevy Trainer on; a session left in the data folder goes (section 6).
        store.remove(SESSION)
        store.remove(f"{SESSION}.seed")
    hevy = Hevy(config.hevy_api_key)
    exercises = ExerciseMap.load(overrides=config.custom_exercises)
    app = App(config, hevy, garmin, exercises, hevy_private=hevy_private, wait=wait, nudge=wake.set)
    httpd = server.start(config.http_port, app, buffer)
    try:
        return app.run()
    finally:
        httpd.shutdown()
        httpd.server_close()
