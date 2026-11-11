"""Which Garmin exercise each Hevy exercise becomes (spec section 7).

Two tables ship with the app, both plain CSV so a fix is a one-line PR (F-54):

- `data/exercise_map.csv`: one row per built-in Hevy exercise, by template id.
  Seeded from hevy2garmin's HEVY_TO_GARMIN (github.com/drkostas/hevy2garmin, MIT).
- `data/custom_exercise_map.csv`: for a user's own exercises, and for a built-in
  the first table doesn't know yet, by primary muscle group and equipment.
  `*` matches any equipment, and the `*`, `*` row catches everything else.

A user's own exercise can also be given its Garmin exercise in
CUSTOM_EXERCISE_MAP (C-11), which wins over the second table. Its id belongs to
one Hevy account, so no shipped table can hold its row (TJ, 2026-11-10, #24).

`data/garmin_exercises.json` holds the keys of Garmin's own exercise list, so
the app can refuse a CUSTOM_EXERCISE_MAP pair Garmin doesn't have (F-51).
"""

import csv
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data"
GARMIN_EXERCISES = DATA / "garmin_exercises.json"
ANY = "*"


@dataclass(frozen=True)
class GarminExercise:
    category: str
    name: str


def rows(path: Path) -> list[dict[str, str]]:
    """One of the two tables as rows. Lines that start with `#` say where the table came from."""
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def garmin_exercises(path: Path = GARMIN_EXERCISES) -> dict[str, frozenset[str]]:
    """Garmin's category keys, each with its exercise keys: every pair Garmin has (F-51)."""
    categories: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    return {category: frozenset(names) for category, names in categories.items()}


class ExerciseMap:
    def __init__(
        self,
        by_template: dict[str, GarminExercise],
        by_muscle_and_equipment: dict[tuple[str, str], GarminExercise],
        overrides: Mapping[str, GarminExercise] | None = None,
    ) -> None:
        self._by_template = by_template
        self._fallback = by_muscle_and_equipment
        self._overrides = dict(overrides or {})  # CUSTOM_EXERCISE_MAP, by template id or title (C-11)
        self._reported: set[str] = set()
        self._ignored: set[str] = set()
        self._picked: dict[str, GarminExercise] = {}

    @classmethod
    def load(cls, folder: Path = DATA, overrides: Mapping[str, GarminExercise] | None = None) -> ExerciseMap:
        by_template = {
            row["hevy_id"]: GarminExercise(row["garmin_category"], row["garmin_name"])
            for row in rows(folder / "exercise_map.csv")
        }
        fallback = {
            (row["primary_muscle_group"], row["equipment"]): GarminExercise(row["garmin_category"], row["garmin_name"])
            for row in rows(folder / "custom_exercise_map.csv")
        }
        return cls(by_template, fallback, overrides)

    def find(self, template_id: str, title: str, template: Callable[[], dict[str, Any] | None]) -> GarminExercise:
        """The Garmin exercise for one Hevy exercise. `template` reads Hevy's template when the map needs it."""
        mapped = self._by_template.get(template_id)
        if mapped:
            self._ignore_override(template_id, title)
            return mapped
        details = template() or {}
        muscle = str(details.get("primary_muscle_group") or "")
        equipment = str(details.get("equipment") or "")
        if not details.get("is_custom"):
            self._ignore_override(template_id, title)
            if template_id not in self._reported:
                # A built-in the map has no row for, most likely one Hevy added since (F-55).
                self._reported.add(template_id)
                log.warning(
                    "No exercise map row for Hevy exercise %r (%s); using the closest by muscle group and equipment. "
                    "Please report it at https://github.com/zimmertr/hevy-garmin-sync/issues so it gets a proper row.",
                    title,
                    template_id,
                )
            return self._closest(muscle, equipment)

        override = self._override(template_id, title)
        found = override or self._closest(muscle, equipment)
        if self._picked.get(template_id) != found:
            # Once per exercise, and again if the pick changes, since nothing else shows a user the guess (#24).
            self._picked[template_id] = found
            how = "from CUSTOM_EXERCISE_MAP" if override else "by muscle group and equipment"
            log.info(
                "Custom Hevy exercise %r (muscle group %s, equipment %s) is Garmin's %s / %s, %s",
                title,
                muscle,
                equipment,
                found.category,
                found.name,
                how,
            )
        return found

    def _override(self, template_id: str, title: str) -> GarminExercise | None:
        """The CUSTOM_EXERCISE_MAP entry for one exercise: its template id first, then its title (C-11)."""
        return self._overrides.get(template_id) or self._overrides.get(title.strip())

    def _ignore_override(self, template_id: str, title: str) -> None:
        # Whether a title is built-in is only known once Hevy's template is read, so this can't be refused at
        # startup; and a built-in's row belongs in the shipped table, for every user (F-54, TJ, 2026-11-10, #24).
        if self._override(template_id, title) and template_id not in self._ignored:
            self._ignored.add(template_id)
            log.warning(
                "CUSTOM_EXERCISE_MAP names %r, a built-in Hevy exercise, and is ignored for it: the variable is for "
                "your own exercises. If its Garmin exercise is wrong, please report it at "
                "https://github.com/zimmertr/hevy-garmin-sync/issues so the exercise map gets fixed.",
                title,
            )

    def _closest(self, muscle: str, equipment: str) -> GarminExercise:
        for key in ((muscle, equipment), (muscle, ANY), (ANY, ANY)):
            if key in self._fallback:
                return self._fallback[key]
        raise LookupError("custom_exercise_map.csv has no `*`, `*` row")
