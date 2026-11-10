"""Which Garmin exercise each Hevy exercise becomes (spec section 7).

Two tables ship with the app, both plain CSV so a fix is a one-line PR (F-54):

- `data/exercise_map.csv`: one row per built-in Hevy exercise, by template id.
  Seeded from hevy2garmin's HEVY_TO_GARMIN (github.com/drkostas/hevy2garmin, MIT).
- `data/custom_exercise_map.csv`: for a user's own exercises, and for a built-in
  the first table doesn't know yet, by primary muscle group and equipment.
  `*` matches any equipment, and the `*`, `*` row catches everything else.
"""

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data"
ANY = "*"


@dataclass(frozen=True)
class GarminExercise:
    category: str
    name: str


class ExerciseMap:
    def __init__(
        self,
        by_template: dict[str, GarminExercise],
        by_muscle_and_equipment: dict[tuple[str, str], GarminExercise],
    ) -> None:
        self._by_template = by_template
        self._fallback = by_muscle_and_equipment
        self._reported: set[str] = set()

    @classmethod
    def load(cls, folder: Path = DATA) -> ExerciseMap:
        with (folder / "exercise_map.csv").open(newline="", encoding="utf-8") as f:
            by_template = {
                row["hevy_id"]: GarminExercise(row["garmin_category"], row["garmin_name"]) for row in csv.DictReader(f)
            }
        with (folder / "custom_exercise_map.csv").open(newline="", encoding="utf-8") as f:
            fallback = {
                (row["primary_muscle_group"], row["equipment"]): GarminExercise(
                    row["garmin_category"], row["garmin_name"]
                )
                for row in csv.DictReader(f)
            }
        return cls(by_template, fallback)

    def find(self, template_id: str, title: str, template: Callable[[], dict[str, Any] | None]) -> GarminExercise:
        """The Garmin exercise for one Hevy exercise. `template` reads Hevy's template when the map needs it."""
        mapped = self._by_template.get(template_id)
        if mapped:
            return mapped
        details = template() or {}
        if not details.get("is_custom") and template_id not in self._reported:
            # A built-in the map has no row for, most likely one Hevy added since (F-55).
            self._reported.add(template_id)
            log.warning(
                "No exercise map row for Hevy exercise %r (%s); using the closest by muscle group and equipment. "
                "Please report it at https://github.com/zimmertr/hevy-garmin-sync/issues so it gets a proper row.",
                title,
                template_id,
            )
        muscle = str(details.get("primary_muscle_group") or "")
        equipment = str(details.get("equipment") or "")
        for key in ((muscle, equipment), (muscle, ANY), (ANY, ANY)):
            if key in self._fallback:
                return self._fallback[key]
        raise LookupError("custom_exercise_map.csv has no `*`, `*` row")
