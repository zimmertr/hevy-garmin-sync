"""A Hevy exercise finds its Garmin exercise: by id, else by muscle group and equipment (spec F-50 to F-55)."""

import tempfile
import unittest
from pathlib import Path
from typing import Any

from hevy_garmin_sync.exercises import ExerciseMap, GarminExercise
from tests import fixtures


def no_template() -> dict[str, Any] | None:
    raise AssertionError("a mapped exercise must not read its template")


class FindTest(unittest.TestCase):
    def setUp(self) -> None:
        self.map = fixtures.exercise_map()

    def find(self, template_id: str, template: dict[str, Any] | None) -> GarminExercise:
        return self.map.find(template_id, "Some Exercise", lambda: template)

    def test_a_built_in_exercise_is_found_by_its_id_without_reading_hevy(self) -> None:
        found = self.map.find("T-BENCH", "Bench Press (Barbell)", no_template)
        self.assertEqual(found, GarminExercise("BENCH_PRESS", "BARBELL_BENCH_PRESS"))

    def test_a_custom_exercise_goes_by_muscle_group_and_equipment(self) -> None:
        custom = fixtures.hevy_template("T-MINE", "My Curl", is_custom=True, primary_muscle_group="biceps")
        with self.assertNoLogs("hevy_garmin_sync.exercises"):
            self.assertEqual(
                self.find("T-MINE", custom | {"equipment": "dumbbell"}), GarminExercise("CURL", "DUMBBELL_BICEPS_CURL")
            )
            self.assertEqual(self.find("T-MINE", custom | {"equipment": "machine"}), GarminExercise("CURL", "CURL"))
            self.assertEqual(
                self.find("T-MINE", custom | {"primary_muscle_group": "neck"}),
                GarminExercise("TOTAL_BODY", "TOTAL_BODY"),
            )

    def test_a_built_in_the_map_lacks_falls_back_and_asks_once_to_be_reported(self) -> None:
        added = fixtures.hevy_template("T-ADDED", "Zottman Curl", primary_muscle_group="biceps", equipment="dumbbell")
        with self.assertLogs("hevy_garmin_sync.exercises", "WARNING") as logs:
            found = self.map.find("T-ADDED", "Zottman Curl", lambda: added)
        self.assertEqual(found, GarminExercise("CURL", "DUMBBELL_BICEPS_CURL"))
        self.assertIn("'Zottman Curl'", logs.output[0])
        self.assertIn("report it", logs.output[0])
        with self.assertNoLogs("hevy_garmin_sync.exercises"):
            self.map.find("T-ADDED", "Zottman Curl", lambda: added)

    def test_an_exercise_hevy_knows_nothing_about_gets_the_catch_all(self) -> None:
        with self.assertLogs("hevy_garmin_sync.exercises", "WARNING"):
            self.assertEqual(self.find("T-GONE", None), GarminExercise("TOTAL_BODY", "TOTAL_BODY"))

    def test_a_fallback_table_with_no_catch_all_is_an_error(self) -> None:
        broken = ExerciseMap({}, {("biceps", "*"): GarminExercise("CURL", "CURL")})
        custom = fixtures.hevy_template("T-MINE", "My Press", is_custom=True)
        with self.assertRaises(LookupError):
            broken.find("T-MINE", "My Press", lambda: custom)


class LoadTest(unittest.TestCase):
    def test_both_tables_are_read_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "exercise_map.csv").write_text(
                "hevy_id,hevy_title,garmin_category,garmin_name,strava_name,observed_date\n"
                'T-BENCH,"Bench Press (Barbell)",BENCH_PRESS,BARBELL_BENCH_PRESS,,\n',
                encoding="utf-8",
            )
            Path(folder, "custom_exercise_map.csv").write_text(
                "primary_muscle_group,equipment,garmin_category,garmin_name\n*,*,TOTAL_BODY,TOTAL_BODY\n",
                encoding="utf-8",
            )
            loaded = ExerciseMap.load(Path(folder))
        self.assertEqual(
            loaded.find("T-BENCH", "Bench Press (Barbell)", no_template),
            GarminExercise("BENCH_PRESS", "BARBELL_BENCH_PRESS"),
        )
        custom = fixtures.hevy_template("T-MINE", "My Press", is_custom=True)
        self.assertEqual(loaded.find("T-MINE", "My Press", lambda: custom), GarminExercise("TOTAL_BODY", "TOTAL_BODY"))


if __name__ == "__main__":
    unittest.main()
