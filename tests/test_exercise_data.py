"""The two tables the app ships: every row names an exercise Garmin has (spec F-51).

`tests/data/garmin_exercises.json` holds the category and exercise keys of
Garmin Connect's own list, https://connect.garmin.com/web-data/exercises/Exercises.json,
as read on 2026-11-10.
"""

import json
import unittest
from pathlib import Path

from hevy_garmin_sync import exercises

GARMIN: dict[str, list[str]] = json.loads(
    (Path(__file__).parent / "data" / "garmin_exercises.json").read_text(encoding="utf-8")
)
# The values Hevy's public API gives an exercise template (its OpenAPI spec, 2026-11-10).
MUSCLE_GROUPS = {
    "abdominals",
    "shoulders",
    "biceps",
    "triceps",
    "forearms",
    "quadriceps",
    "hamstrings",
    "calves",
    "glutes",
    "abductors",
    "adductors",
    "lats",
    "upper_back",
    "traps",
    "lower_back",
    "chest",
    "cardio",
    "neck",
    "full_body",
    "other",
}
EQUIPMENT = {"none", "barbell", "dumbbell", "kettlebell", "machine", "plate", "resistance_band", "suspension", "other"}


class ExerciseDataTest(unittest.TestCase):
    def assert_garmin_has(self, row: dict[str, str]) -> None:
        self.assertIn(row["garmin_name"], GARMIN.get(row["garmin_category"], ()), row)

    def test_every_built_in_row_names_a_garmin_exercise(self) -> None:
        rows = exercises.rows(exercises.DATA / "exercise_map.csv")
        self.assertGreater(len(rows), 400)
        for row in rows:
            with self.subTest(hevy_id=row["hevy_id"]):
                self.assert_garmin_has(row)

    def test_the_built_in_table_has_its_six_columns_and_one_row_per_hevy_exercise(self) -> None:
        rows = exercises.rows(exercises.DATA / "exercise_map.csv")
        self.assertEqual(
            list(rows[0]), ["hevy_id", "hevy_title", "garmin_category", "garmin_name", "strava_name", "observed_date"]
        )
        ids = [row["hevy_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("", ids)

    def test_every_fallback_row_names_a_garmin_exercise_for_a_muscle_group_and_equipment_hevy_has(self) -> None:
        rows = exercises.rows(exercises.DATA / "custom_exercise_map.csv")
        for row in rows:
            with self.subTest(row=row):
                self.assert_garmin_has(row)
                self.assertIn(row["primary_muscle_group"], MUSCLE_GROUPS | {exercises.ANY})
                self.assertIn(row["equipment"], EQUIPMENT | {exercises.ANY})
        keys = [(row["primary_muscle_group"], row["equipment"]) for row in rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_fallback_table_catches_everything(self) -> None:
        rows = exercises.rows(exercises.DATA / "custom_exercise_map.csv")
        self.assertIn((exercises.ANY, exercises.ANY), {(row["primary_muscle_group"], row["equipment"]) for row in rows})

    def test_the_tables_load(self) -> None:
        loaded = exercises.ExerciseMap.load()
        found = loaded.find("no-such-id", "My Own", lambda: {"is_custom": True, "primary_muscle_group": "other"})
        self.assertEqual((found.category, found.name), ("CORE", "CORE"))


if __name__ == "__main__":
    unittest.main()
