"""Make Garmin match the plan: workouts, Send to Device, and today's calendar (spec F-3, sections 3 and 5).

A full run reads Garmin's workout list and calendar first, and happens at
startup, at local midnight, and after Garmin comes back from a failure. Every
other run works from what the last run left in memory and calls Garmin only for
what changed in Hevy (F-4a), including a workout that moved on or off today's
calendar (F-31, #25), and for a workout Garmin refused once its retry is due
(F-16, #4).
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from . import workout
from .errors import Refused
from .garmin import Garmin
from .workout import Workout

log = logging.getLogger(__name__)

Key = tuple[str, str]  # a workout's kind and its Hevy id
_CALENDAR_DAYS_BACK = 31  # F-32
_FIRST_RETRY = timedelta(minutes=5)  # after Garmin refuses a workout, doubling until midnight (F-16, #4)


@dataclass(frozen=True)
class Plans:
    """What one source (routines, or Hevy Trainer) wants in Garmin right now."""

    kind: str
    workouts: Sequence[Workout]
    # Keep this kind's Garmin workouts even when they are not listed: the
    # source could not say for sure that they are gone (F-14a).
    hold: bool = False
    # Hevy ids that get no calendar entry today (F-31, F-33). A change moves
    # the entry in the same run, or at the next full run when its id is unknown.
    off_calendar: frozenset[str] = frozenset()


@dataclass
class Counts:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    scheduled: int = 0
    unscheduled: int = 0
    failed: int = 0

    def any(self) -> bool:
        return any(vars(self).values())

    def __str__(self) -> str:
        return ", ".join(f"{name} {count}" for name, count in vars(self).items())


@dataclass
class _Known:
    """One of the app's workouts in Garmin, as of the last run."""

    workout_id: int
    version: str | None


@dataclass
class _Refused:
    """A version of a workout Garmin refused, and when to try it again (F-16)."""

    version: str
    day: date  # the local day of the last refusal
    gap: timedelta
    # The next try between full runs, in UTC so a clock change can't move it. None once
    # it has been refused across a midnight: from then on only a full run tries it.
    due: datetime | None


@dataclass
class Sync:
    garmin: Garmin
    scheduled: bool  # ENABLE_SCHEDULED_WORKOUTS (F-30a)
    now: Callable[[], datetime]  # the current time in the user's zone
    _system: str | None = None
    _known: dict[Key, _Known] = field(default_factory=dict)
    _refused: dict[Key, _Refused] = field(default_factory=dict)  # F-16
    _absent: set[Key] = field(default_factory=set)
    _empty: set[Key] = field(default_factory=set)
    _unsent: list[int] = field(default_factory=list)
    _entries: dict[int, int] = field(default_factory=dict)  # workout id -> today's calendar entry
    # Workouts on today's calendar, also those whose entry id Garmin did not give,
    # so a poll never schedules one twice.
    _on_today: set[int] = field(default_factory=set)
    _no_device_reported: bool = False

    def run(self, plans: Sequence[Plans], full: bool) -> Counts:
        counts = Counts()
        today = self.now().date()
        if full:
            self._read_garmin(counts)
        self._send()
        desired = self._desired(plans)
        off_calendar = {(p.kind, source_id) for p in plans for source_id in p.off_calendar}
        for key, plan in desired.items():
            self._write(key, plan, key in off_calendar, today, full, counts)
        self._delete_missing(desired, {p.kind for p in plans if p.hold}, counts)
        if full:
            self._reconcile_calendar(today, off_calendar, counts)
        elif self.scheduled:
            self._follow_calendar(desired, off_calendar, today, counts)
        return counts

    def _read_garmin(self, counts: Counts) -> None:
        self._system = self.garmin.measurement_system()
        self._known = {}
        for item in self.garmin.workouts():
            owner = workout.owner(item.get("description"))
            if not owner:
                continue  # not the app's: never touched (F-12)
            key = (owner.kind, owner.source_id)
            if key in self._known:
                log.warning("Two Garmin workouts claim %s %s; deleting %r", *key, item.get("workoutName"))
                self.garmin.delete(int(item["workoutId"]))
                counts.deleted += 1
            else:
                self._known[key] = _Known(int(item["workoutId"]), owner.version)

    def _desired(self, plans: Sequence[Plans]) -> dict[Key, Workout]:
        desired = {}
        empty = set()
        for plan in (w for p in plans for w in p.workouts):
            key = (plan.kind, plan.source_id)
            if any(exercise.sets for exercise in plan.exercises):
                desired[key] = plan
            else:
                empty.add(key)
                if key not in self._empty:
                    log.info("%r has no exercises, so it gets no Garmin workout", plan.name)
        self._empty = empty
        return desired

    def _write(self, key: Key, plan: Workout, off_calendar: bool, today: date, full: bool, counts: Counts) -> None:
        body = workout.build(plan, self._system)
        version = workout.version(body)
        known = self._known.get(key)
        if known and known.version == version:
            return
        refused = self._refused.get(key)
        if refused and refused.version != version:
            refused = None  # changed in Hevy, so it is tried at once and its gaps start over
        if refused:
            # Only a full run or a retry that is due calls Garmin again, never every poll (F-4a, F-16).
            if not full and (refused.due is None or self.now() < refused.due):
                return
            log.info("Trying %r again, which Garmin refused", plan.name)
        stamped = workout.stamped(body, plan, self.now())
        try:
            if known:
                self.garmin.update(known.workout_id, stamped)
            else:
                created = self.garmin.create(stamped)
        except Refused as e:
            counts.failed += 1
            next_try = self._refuse(key, version, refused, today)
            log.error(
                "Garmin refused %r (%d steps): %s. It is tried again %s, or as soon as the routine changes.",
                plan.name,
                workout.step_count(body),
                e,
                next_try,
            )
            return
        self._refused.pop(key, None)
        if known:
            known.version = version
            counts.updated += 1
            log.debug("Updated %r", plan.name)
        else:
            known = self._known[key] = _Known(created, version)
            counts.created += 1
            log.debug("Created %r", plan.name)
            if self.scheduled and not off_calendar:
                self._schedule(created, today, counts)
        self._unsent.append(known.workout_id)
        self._send()

    def _refuse(self, key: Key, version: str, before: _Refused | None, today: date) -> str:
        """Note that Garmin refused this version, and say when it is tried next (F-16; TJ, 2026-11-10, #4).

        The gaps start at 5 minutes and double until local midnight. The full
        run at midnight tries it once more, and one refused there too is tried
        once a day from then on. A full run on the same day (after a Garmin
        failure) also tries it, and doubles the gap like any other try.
        """
        now = self.now()
        if before is None:
            refused = _Refused(version, today, _FIRST_RETRY, now.astimezone(UTC) + _FIRST_RETRY)
        elif before.day < today:
            refused = _Refused(version, today, before.gap, None)
        elif before.due is None:
            refused = before
        else:
            refused = _Refused(version, today, before.gap * 2, now.astimezone(UTC) + before.gap * 2)
        self._refused[key] = refused
        due = refused.due.astimezone(now.tzinfo) if refused.due else None
        return f"at {due:%H:%M}" if due and due.date() == today else "at midnight"

    def _send(self) -> None:
        """Send every created or changed workout to the watch (F-31a).

        A workout stays queued when Garmin fails, so the send is retried with
        the next run instead of being lost.
        """
        while self._unsent:
            try:
                self.garmin.send_to_device(self._unsent[0])
            except Refused as e:
                if not self._no_device_reported:
                    self._no_device_reported = True
                    log.warning(
                        "Garmin did not take a workout for the watch's saved list (%s). It is still on the "
                        "calendar. Does the account have a watch that has synced?",
                        e,
                    )
            self._unsent.pop(0)

    def _delete_missing(self, desired: dict[Key, Workout], held: set[str], counts: Counts) -> None:
        """Delete workouts whose routine is gone, once two runs in a row agree that it is.

        Hevy's lists are read a page at a time, so a routine can be missing
        from one read while the list shifts under it. A deleted workout stays
        in the watch's saved list (F-14), so deleting on one bad read would
        leave a stale copy there for good.
        """
        gone = {key for key in self._known if key not in desired and key[0] not in held}
        for key in gone & self._absent:
            known = self._known.pop(key)
            if known.workout_id in self._entries:
                self.garmin.unschedule(self._entries.pop(known.workout_id))
                counts.unscheduled += 1
            self._on_today.discard(known.workout_id)
            self.garmin.delete(known.workout_id)
            counts.deleted += 1
            log.debug("Deleted the Garmin workout of %s %s", *key)
        self._absent = gone & self._known.keys()

    def _schedule(self, workout_id: int, day: date, counts: Counts) -> None:
        entry = self.garmin.schedule(workout_id, day)
        self._on_today.add(workout_id)
        if entry is not None:
            self._entries[workout_id] = entry
        counts.scheduled += 1

    def _follow_calendar(
        self, desired: dict[Key, Workout], off_calendar: set[Key], today: date, counts: Counts
    ) -> None:
        """Between full runs, move a workout on or off today as soon as its source says so (F-31, #25).

        Hevy Trainer moves its next workout when one is logged or the program
        is reordered, and the watch should follow within a poll, not at
        midnight. This reads no calendar (F-4a): it works from the entries the
        last runs made, so one whose id Garmin did not give stays until the
        next full run. Only listed workouts move, so a held kind's (F-14a) and
        a deleted routine's entries are left to the paths that handle them.
        The old entry goes before the new one is added, as at a full run.
        """
        listed = [(self._known[key].workout_id, key in off_calendar) for key in desired if key in self._known]
        for workout_id, off in listed:
            if off and workout_id in self._entries:
                self.garmin.unschedule(self._entries.pop(workout_id))
                self._on_today.discard(workout_id)
                counts.unscheduled += 1
        for workout_id, off in listed:
            if not off and workout_id not in self._on_today:
                self._schedule(workout_id, today, counts)

    def _reconcile_calendar(self, today: date, off_calendar: set[Key], counts: Counts) -> None:
        """One entry on today for each workout, and none of the app's on the 31 days before (F-31, F-32).

        Entries of workouts the app doesn't own are never touched, entries on
        later days are left alone, and whether an entry was completed is never
        read: the recorded activity stays on Garmin's calendar by itself.
        """
        mine = {known.workout_id: key for key, known in self._known.items()}
        self._entries = {}
        self._on_today = set()
        for entry in self.garmin.scheduled(today - timedelta(days=_CALENDAR_DAYS_BACK), today):
            workout_id = (entry.get("workout") or {}).get("workoutId")
            entry_id = entry.get("workoutScheduleId")
            if workout_id not in mine or entry_id is None:
                continue
            wanted = (
                self.scheduled
                and entry.get("calendarDate") == today.isoformat()
                and workout_id not in self._entries
                and mine[workout_id] not in off_calendar
            )
            if wanted:
                self._entries[workout_id] = int(entry_id)
                self._on_today.add(workout_id)
            else:
                self.garmin.unschedule(int(entry_id))
                counts.unscheduled += 1
        if self.scheduled:
            for key, known in self._known.items():
                if known.workout_id not in self._entries and key not in off_calendar:
                    self._schedule(known.workout_id, today, counts)
