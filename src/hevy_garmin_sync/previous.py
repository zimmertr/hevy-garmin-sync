"""Last time's working sets of each exercise, for the note on the watch (spec F-30, #3).

Last time is the newest logged workout, any workout, that holds the exercise
and a working set of it. That is Hevy's default for its PREVIOUS column, and
the app uses it for routines and Hevy Trainer workouts alike, whatever Hevy's
"Previous Workout Values" setting says (TJ, 2026-11-11). Everything comes from
the public API, so a user without HEVY_SESSION gets it too.

Kept in memory only: an exercise's history is read the first time it is asked
for, and the workout events keep it current after that (F-4).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .hevy import Hevy
from .hevy_private import parse_time
from .workout import LoggedSet

Json = dict[str, Any]
_HISTORY_DAYS = 365
_EARLIEST = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class _Last:
    """One exercise's last session: no workout and no sets when it has none."""

    workout_id: str | None = None
    started: datetime | None = None
    sets: tuple[LoggedSet, ...] = ()


class Previous:
    def __init__(self, hevy: Hevy, now: Callable[[], datetime]) -> None:
        self._hevy = hevy
        self._now = now
        self._kept: dict[str, _Last] = {}  # by exercise template id

    def sets(self, template_id: str) -> tuple[LoggedSet, ...]:
        """The working sets of the exercise's last session, or none. One history read per exercise, ever."""
        if not template_id:
            return ()
        if template_id not in self._kept:
            now = self._now()
            rows = self._hevy.exercise_history(template_id, now - timedelta(days=_HISTORY_DAYS), now)
            self._kept[template_id] = _newest(rows)
        return self._kept[template_id].sets

    def update(self, events: Sequence[Json]) -> None:
        """Follow saved, edited and deleted workouts, so no history is read again unless it must be."""
        # Hevy lists the events newest first. Oldest first here, so a workout saved twice ends as it was last saved.
        for event in reversed(events):
            if event.get("type") == "updated":
                self._updated(event.get("workout") or {})
            elif event.get("type") == "deleted":
                # The reference gives a deleted event the workout's id alone; the whole workout is read too, in case.
                gone = event.get("id") or (event.get("workout") or {}).get("id")
                self._kept = {k: last for k, last in self._kept.items() if last.workout_id != str(gone)}

    def _updated(self, workout: Json) -> None:
        workout_id = str(workout.get("id") or "")
        started = parse_time(workout.get("start_time"))
        held: dict[str, list[LoggedSet]] = {}  # each exercise in it, with its working sets
        for exercise in workout.get("exercises") or []:
            sets = held.setdefault(str(exercise.get("exercise_template_id") or ""), [])
            sets.extend(_logged(s) for s in exercise.get("sets") or [] if s.get("type") != "warmup")
        # An exercise not kept yet is left alone: its first ask reads a history that holds this workout.
        for template_id, last in list(self._kept.items()):
            working = held.get(template_id)
            if workout_id and last.workout_id == workout_id and not working:
                # Its last session no longer holds it, and which one does now is in its history alone.
                del self._kept[template_id]
            elif working and (last.workout_id == workout_id or (started or _EARLIEST) >= (last.started or _EARLIEST)):
                self._kept[template_id] = _Last(workout_id, started, tuple(working))


def _newest(rows: Sequence[Json]) -> _Last:
    """The newest workout in an exercise's history that holds a working set of it."""
    sessions: dict[str, _Last] = {}
    for row in rows:
        if row.get("set_type") == "warmup":
            continue
        workout_id = str(row.get("workout_id") or "")
        found = sessions.get(workout_id) or _Last(workout_id, parse_time(row.get("workout_start_time")))
        sessions[workout_id] = _Last(found.workout_id, found.started, (*found.sets, _logged(row)))
    return max(sessions.values(), key=lambda last: last.started or _EARLIEST, default=_Last())


def _logged(row: Json) -> LoggedSet:
    """A set of the history or of a workout event: both name the fields alike."""
    weight, reps, rpe, seconds, meters = (
        row.get(key) for key in ("weight_kg", "reps", "rpe", "duration_seconds", "distance_meters")
    )
    return LoggedSet(
        weight_kg=float(weight) if weight else None,
        reps=int(reps) if reps else None,
        rpe=float(rpe) if rpe else None,
        seconds=int(seconds) if seconds else None,
        meters=float(meters) if meters else None,
    )
