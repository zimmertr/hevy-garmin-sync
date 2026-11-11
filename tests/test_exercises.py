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
        with self.assertNoLogs("hevy_garmin_sync.exercises", "WARNING"):
            self.assertEqual(
                self.find("T-MINE", custom | {"equipment": "dumbbell"}), GarminExercise("CURL", "DUMBBELL_BICEPS_CURL")
            )
            self.assertEqual(self.find("T-MINE", custom | {"equipment": "machine"}), GarminExercise("CURL", "CURL"))
            self.assertEqual(
                self.find("T-MINE", custom | {"primary_muscle_group": "neck"}),
                GarminExercise("TOTAL_BODY", "TOTAL_BODY"),
            )


class PickTest(unittest.TestCase):
    """A custom exercise's Garmin exercise is logged, and CUSTOM_EXERCISE_MAP can set it (#24, C-11, F-53)."""

    raise_ = GarminExercise("LATERAL_RAISE", "CABLE_FRONT_RAISE")

    def setUp(self) -> None:
        self.custom = fixtures.hevy_template(
            "T-MINE", "My Cable Raise", is_custom=True, primary_muscle_group="shoulders", equipment="cable"
        )

    def test_the_pick_is_logged_once_per_exercise_with_what_it_came_from(self) -> None:
        exercises = fixtures.exercise_map()
        with self.assertLogs("hevy_garmin_sync.exercises", "INFO") as logs:
            found = exercises.find("T-MINE", "My Cable Raise", lambda: self.custom)
            exercises.find("T-MINE", "My Cable Raise", lambda: self.custom)
            exercises.find("T-OTHER", "My Curl", lambda: self.custom | {"primary_muscle_group": "biceps"})
        self.assertEqual(found, GarminExercise("TOTAL_BODY", "TOTAL_BODY"))
        self.assertEqual(
            logs.output,
            [
                "INFO:hevy_garmin_sync.exercises:Custom Hevy exercise 'My Cable Raise' (muscle group shoulders, "
                "equipment cable) is Garmin's TOTAL_BODY / TOTAL_BODY, by muscle group and equipment",
                "INFO:hevy_garmin_sync.exercises:Custom Hevy exercise 'My Curl' (muscle group biceps, "
                "equipment cable) is Garmin's CURL / CURL, by muscle group and equipment",
            ],
        )

    def test_a_pick_that_changes_is_logged_again(self) -> None:
        exercises = fixtures.exercise_map()
        with self.assertLogs("hevy_garmin_sync.exercises", "INFO") as logs:
            exercises.find("T-MINE", "My Cable Raise", lambda: self.custom)
            exercises.find("T-MINE", "My Cable Raise", lambda: self.custom | {"primary_muscle_group": "biceps"})
        self.assertEqual(len(logs.output), 2)
        self.assertIn("CURL / CURL", logs.output[1])

    def test_an_entry_by_title_wins_over_the_fallback_table(self) -> None:
        exercises = fixtures.exercise_map({"My Cable Raise": self.raise_})
        with self.assertLogs("hevy_garmin_sync.exercises", "INFO") as logs:
            self.assertEqual(exercises.find("T-MINE", " My Cable Raise ", lambda: self.custom), self.raise_)
        self.assertEqual(
            logs.output,
            [
                "INFO:hevy_garmin_sync.exercises:Custom Hevy exercise ' My Cable Raise ' (muscle group shoulders, "
                "equipment cable) is Garmin's LATERAL_RAISE / CABLE_FRONT_RAISE, from CUSTOM_EXERCISE_MAP",
            ],
        )

    def test_an_entry_by_id_is_tried_before_one_by_title(self) -> None:
        by_id = GarminExercise("SHOULDER_PRESS", "SHOULDER_PRESS")
        exercises = fixtures.exercise_map({"My Cable Raise": self.raise_, "T-MINE": by_id})
        with self.assertLogs("hevy_garmin_sync.exercises", "INFO"):
            self.assertEqual(exercises.find("T-MINE", "My Cable Raise", lambda: self.custom), by_id)

    def test_a_title_matches_only_exactly_and_with_its_case(self) -> None:
        exercises = fixtures.exercise_map({"my cable raise": self.raise_, "My Cable": self.raise_})
        with self.assertLogs("hevy_garmin_sync.exercises", "INFO"):
            found = exercises.find("T-MINE", "My Cable Raise", lambda: self.custom)
        self.assertEqual(found, GarminExercise("TOTAL_BODY", "TOTAL_BODY"))

    def test_an_entry_naming_a_built_in_is_ignored_with_one_warning(self) -> None:
        exercises = fixtures.exercise_map(
            {"Bench Press (Barbell)": self.raise_, "T-ADDED": self.raise_, "T-BENCH": self.raise_}
        )
        added = fixtures.hevy_template("T-ADDED", "Zottman Curl", primary_muscle_group="biceps", equipment="dumbbell")
        with self.assertLogs("hevy_garmin_sync.exercises", "WARNING") as logs:
            for _ in range(2):
                bench = exercises.find("T-BENCH", "Bench Press (Barbell)", no_template)
                zottman = exercises.find("T-ADDED", "Zottman Curl", lambda: added)
        self.assertEqual(bench, GarminExercise("BENCH_PRESS", "BARBELL_BENCH_PRESS"))
        self.assertEqual(zottman, GarminExercise("CURL", "DUMBBELL_BICEPS_CURL"))
        ignored = [line for line in logs.output if "CUSTOM_EXERCISE_MAP" in line]
        self.assertEqual(len(ignored), 2)
        self.assertIn("names 'Bench Press (Barbell)', a built-in Hevy exercise, and is ignored", ignored[0])
        self.assertIn("names 'Zottman Curl', a built-in Hevy exercise", ignored[1])
        self.assertEqual(len(logs.output), 3)  # and the one asking for Zottman Curl's map row (F-55)

    def test_the_tables_load_with_the_overrides(self) -> None:
        loaded = ExerciseMap.load(overrides={"My Cable Raise": self.raise_})
        with self.assertLogs("hevy_garmin_sync.exercises", "INFO"):
            self.assertEqual(loaded.find("no-such-id", "My Cable Raise", lambda: self.custom), self.raise_)

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
                "# A line that says where the table came from, which is not a row.\n"
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
