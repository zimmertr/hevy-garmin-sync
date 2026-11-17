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


def missing(entries: Sequence[str], items: Sequence[Json]) -> list[str]:
    """The entries that name none of the folders or routines, by id or by exact title (C-3, C-16)."""
    return [entry for entry in entries if not _matching(entry, items)]


def _matching(entry: str, items: Sequence[Json]) -> set[Any]:
    """The folders or routines one entry selects: the one with that id, else every one with that title."""
    by_id = {i["id"] for i in items if str(i["id"]) == entry}
    return by_id or {i["id"] for i in items if i.get("title") == entry}


class Routines:
    def __init__(
        self,
        hevy: Hevy,
        folders: Sequence[str],  # INCLUDE_HEVY_FOLDERS
        exercises: ExerciseMap,
        previous: Previous | None = None,  # None: ENABLE_PREVIOUS_VALUES is false
        *,
        routines: Sequence[str] = (),  # INCLUDE_HEVY_ROUTINES
    ) -> None:
        self._hevy = hevy
        self._folders = tuple(folders)
        self._routines = tuple(routines)
        self._exercises = exercises
        self._previous = previous
        self._missing: list[tuple[str, str]] = []  # (variable, entry), each logged once while it stays missing

    def check(self) -> None:
        """At startup: list every folder, and every routine once either is chosen, so ids can be copied (F-11).

        Refuses a setting that names none (C-3, C-16). Also the first call with the API key, so a rejected key
        shows here.
        """
        folders = self._hevy.folders()
        for folder in folders:
            log.info("Hevy routine folder: id %s, title %r", folder["id"], folder.get("title"))
        if not folders:
            log.info("Hevy has no routine folders")
        routines: list[Json] = []
        if self._folders or self._routines:
            routines = list({r["id"]: r for r in self._hevy.routines()}.values())
            for routine in routines:
                log.info("Hevy routine: id %s, title %r", routine["id"], routine.get("title"))
        unknown = missing(self._folders, folders)
        if unknown:
            raise ConfigError(
                f"INCLUDE_HEVY_FOLDERS names no Hevy folder: {', '.join(unknown)}. "
                "Use a folder's id or its exact title from the list above."
            )
        unknown = missing(self._routines, routines)
        if unknown:
            raise ConfigError(
                f"INCLUDE_HEVY_ROUTINES names no Hevy routine: {', '.join(unknown)}. "
                "Use a routine's id or its exact title from the list above."
            )

    def plans(self) -> Plans:
        """Every selected routine as a planned workout. Raises unless Hevy returned both whole lists (F-14a)."""
        folders = self._hevy.folders()
        routines = {r["id"]: r for r in self._hevy.routines()}
        titles = {f["id"]: str(f.get("title") or "") for f in folders}

        gone = [("INCLUDE_HEVY_FOLDERS", entry) for entry in missing(self._folders, folders)]
        gone += [("INCLUDE_HEVY_ROUTINES", entry) for entry in missing(self._routines, list(routines.values()))]
        for variable, entry in gone:
            if (variable, entry) not in self._missing:
                folder = variable == "INCLUDE_HEVY_FOLDERS"
                kept = "Its routines' Garmin workouts are kept as they are" if folder else "Its Garmin workout is kept"
                log.error(
                    "The Hevy %s %r in %s is gone (deleted or renamed). %s; fix the setting and restart.",
                    "folder" if folder else "routine",
                    entry,
                    variable,
                    kept,
                )
        self._missing = gone
        chosen = bool(self._folders or self._routines)
        folder_ids = set().union(*(_matching(entry, folders) for entry in self._folders))
        routine_ids = set().union(*(_matching(entry, list(routines.values())) for entry in self._routines))

        hold = bool(gone)
        workouts = []
        for routine in routines.values():
            folder_id = routine.get("folder_id")
            # A routine syncs when its folder or the routine itself is chosen, or when nothing is (F-10).
            if chosen and folder_id not in folder_ids and routine["id"] not in routine_ids:
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
        return Workout(
            ROUTINE,
            str(routine["id"]),
            name,
            tuple(self._exercise(e) for e in exercises),
            title=title,
            folder=folder_title,
        )

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
            previous=self._previous.sets(template_id, title) if self._previous else (),
            chosen_by=garmin.chosen_by,
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
