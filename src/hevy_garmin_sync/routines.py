"""Hevy routines: which ones sync, what each is called, and the workout each becomes (spec F-10 to F-15)."""

import logging
from collections.abc import Sequence
from typing import Any

from .errors import ConfigError
from .exercises import ExerciseMap
from .hevy import ASSISTED, Hevy
from .previous import Previous
from .sync import Plans
from .workout import ROUTINE, Exercise, Set, Workout

log = logging.getLogger(__name__)

Json = dict[str, Any]
_SET_TYPES = ("normal", "warmup", "dropset", "failure")


def missing_folders(entries: Sequence[str], folders: Sequence[Json]) -> list[str]:
    """The INCLUDE_HEVY_FOLDERS entries that name no folder, by id or by exact title."""
    return [entry for entry in entries if not _matching(entry, folders)]


def _matching(entry: str, folders: Sequence[Json]) -> set[Any]:
    """The folders one entry selects: the one with that id, else every one with that title (C-3)."""
    by_id = {f["id"] for f in folders if str(f["id"]) == entry}
    return by_id or {f["id"] for f in folders if f.get("title") == entry}


class Routines:
    def __init__(
        self,
        hevy: Hevy,
        entries: Sequence[str],
        exercises: ExerciseMap,
        previous: Previous | None = None,  # None: ENABLE_PREVIOUS_VALUES is false
    ) -> None:
        self._hevy = hevy
        self._entries = tuple(entries)
        self._exercises = exercises
        self._previous = previous
        self._missing: list[str] = []

    def check(self) -> None:
        """At startup: list every folder so ids can be copied (F-11), and refuse a setting that names none (C-3).

        Also the first call with the API key, so a rejected key shows here.
        """
        folders = self._hevy.folders()
        for folder in folders:
            log.info("Hevy routine folder: id %s, title %r", folder["id"], folder.get("title"))
        if not folders:
            log.info("Hevy has no routine folders")
        missing = missing_folders(self._entries, folders)
        if missing:
            raise ConfigError(
                f"INCLUDE_HEVY_FOLDERS names no Hevy folder: {', '.join(missing)}. "
                "Use a folder's id or its exact title from the list above."
            )

    def plans(self) -> Plans:
        """Every selected routine as a planned workout. Raises unless Hevy returned both whole lists (F-14a)."""
        folders = self._hevy.folders()
        routines = {r["id"]: r for r in self._hevy.routines()}
        titles = {f["id"]: str(f.get("title") or "") for f in folders}

        missing = missing_folders(self._entries, folders)
        for entry in missing:
            if entry not in self._missing:
                log.error(
                    "The Hevy folder %r in INCLUDE_HEVY_FOLDERS is gone (deleted or renamed). Its routines' Garmin "
                    "workouts are kept as they are; fix the setting and restart.",
                    entry,
                )
        self._missing = missing
        selected = set().union(*(_matching(entry, folders) for entry in self._entries))

        hold = bool(missing)
        workouts = []
        for routine in routines.values():
            folder_id = routine.get("folder_id")
            if self._entries and folder_id not in selected:
                continue
            if folder_id is not None and folder_id not in titles:
                # The two lists were read a moment apart and disagree. Leave everything alone until they agree.
                hold = True
                continue
            workouts.append(self._plan(routine, titles.get(folder_id)))
        return Plans(ROUTINE, workouts, hold=hold)

    def _plan(self, routine: Json, folder_title: str | None) -> Workout:
        title = str(routine.get("title") or "")
        name = f"Hevy/{folder_title}: {title}" if folder_title is not None else f"Hevy: {title}"
        exercises = sorted(routine.get("exercises") or [], key=lambda e: e.get("index") or 0)
        return Workout(ROUTINE, str(routine["id"]), name, tuple(self._exercise(e) for e in exercises))

    def _exercise(self, exercise: Json) -> Exercise:
        template_id = str(exercise.get("exercise_template_id") or "")
        title = str(exercise.get("title") or "")
        template = self._hevy.template(template_id) or {}
        garmin = self._exercises.find(template_id, title, lambda: template)
        sets = sorted(exercise.get("sets") or [], key=lambda s: s.get("index") or 0)
        return Exercise(
            title=title,
            category=garmin.category,
            name=garmin.name,
            sets=tuple(_set(s) for s in sets),
            rest_seconds=_whole(exercise.get("rest_seconds")),
            superset=_whole(exercise.get("superset_id"), zero=True),
            assisted=template.get("type") in ASSISTED,
            previous=self._previous.sets(template_id) if self._previous else (),
        )


def _set(planned: Json) -> Set:
    kind = planned.get("type")
    reps = _whole(planned.get("reps"))
    rep_range = None
    bounds = planned.get("rep_range") or {}
    start, end = _whole(bounds.get("start")), _whole(bounds.get("end"))
    if start and end and start < end:
        rep_range = (start, end)
    elif start or end:
        # Half a range, or both ends the same: a plain rep target.
        reps = end or start
    weight = planned.get("weight_kg")
    meters = planned.get("distance_meters")
    return Set(
        kind=kind if kind in _SET_TYPES else "normal",
        reps=reps,
        rep_range=rep_range,
        weight_kg=float(weight) if weight else None,
        seconds=_whole(planned.get("duration_seconds")),
        meters=float(meters) if meters else None,
    )


def _whole(value: Any, zero: bool = False) -> int | None:
    """A whole number from Hevy, or None. Zero means none too, except for a superset id, where 0 is the first."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = round(float(value))
    except ValueError:
        return None
    return number if number or zero else None
