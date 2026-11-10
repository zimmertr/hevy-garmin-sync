"""Which routines sync, what each is called, and how a Hevy routine reads as a workout (spec F-10 to F-15)."""

import unittest
from typing import Any

from hevy_garmin_sync import errors, hevy, workout
from hevy_garmin_sync.routines import Routines
from hevy_garmin_sync.workout import Set
from tests import fixtures
from tests.fixtures import hevy_exercise, hevy_folder, hevy_routine, hevy_set


class RoutinesCase(unittest.TestCase):
    def setUp(self) -> None:
        self.api = fixtures.FakeHevyApi()
        self.api.folders = [hevy_folder(42, "Push Pull Legs"), hevy_folder(43, "Home")]
        self.api.routines = [
            hevy_routine("r-push", "Push Day", 42),
            hevy_routine("r-home", "Garage", 43),
            hevy_routine("r-loose", "Stretch"),
        ]

    def routines(self, *entries: str) -> Routines:
        client = hevy.Hevy("made-up-key", self.api)  # type: ignore[arg-type]
        return Routines(client, entries, fixtures.exercise_map())

    def names(self, *entries: str) -> list[str]:
        return [w.name for w in self.routines(*entries).plans().workouts]


class SelectionTest(RoutinesCase):
    def test_every_routine_syncs_by_default(self) -> None:
        self.assertEqual(self.names(), ["Hevy/Push Pull Legs: Push Day", "Hevy/Home: Garage", "Hevy: Stretch"])

    def test_a_folder_is_chosen_by_id_or_by_exact_title(self) -> None:
        self.assertEqual(self.names("42"), ["Hevy/Push Pull Legs: Push Day"])
        self.assertEqual(self.names("Home"), ["Hevy/Home: Garage"])
        self.assertEqual(self.names("Home", "42"), ["Hevy/Push Pull Legs: Push Day", "Hevy/Home: Garage"])

    def test_an_id_is_tried_before_a_title(self) -> None:
        self.api.folders.append(hevy_folder(44, "42"))
        self.api.routines.append(hevy_routine("r-odd", "Odd", 44))
        self.assertEqual(self.names("42"), ["Hevy/Push Pull Legs: Push Day"])

    def test_a_routine_with_no_folder_syncs_only_when_no_folder_is_chosen(self) -> None:
        self.assertNotIn("Hevy: Stretch", self.names("42"))

    def test_the_plans_are_routines_and_are_not_held(self) -> None:
        plans = self.routines().plans()
        self.assertEqual(plans.kind, workout.ROUTINE)
        self.assertFalse(plans.hold)
        self.assertEqual([w.source_id for w in plans.workouts], ["r-push", "r-home", "r-loose"])
        self.assertEqual({w.kind for w in plans.workouts}, {workout.ROUTINE})

    def test_two_routines_may_share_a_name(self) -> None:
        self.api.routines.append(hevy_routine("r-push-2", "Push Day", 42))
        self.assertEqual(self.names("42"), ["Hevy/Push Pull Legs: Push Day"] * 2)

    def test_a_routine_listed_twice_while_the_pages_shift_counts_once(self) -> None:
        self.api.routines.append(self.api.routines[0])
        self.assertEqual(len(self.names()), 3)


class StartupTest(RoutinesCase):
    def test_every_folder_is_logged_with_its_id(self) -> None:
        with self.assertLogs("hevy_garmin_sync.routines", "INFO") as logs:
            self.routines().check()
        self.assertEqual(len(logs.output), 2)
        self.assertIn("id 42, title 'Push Pull Legs'", logs.output[0])

    def test_no_folders_is_said_too(self) -> None:
        self.api.folders = []
        with self.assertLogs("hevy_garmin_sync.routines", "INFO") as logs:
            self.routines().check()
        self.assertIn("no routine folders", logs.output[0])

    def test_an_unknown_folder_exits_after_the_list_is_logged(self) -> None:
        with (
            self.assertLogs("hevy_garmin_sync.routines", "INFO") as logs,
            self.assertRaisesRegex(errors.ConfigError, "INCLUDE_HEVY_FOLDERS names no Hevy folder: Legs, 99"),
        ):
            self.routines("42", "Legs", "99").check()
        self.assertEqual(len(logs.output), 2)

    def test_a_rejected_key_shows_here(self) -> None:
        self.api.fail(401)
        with self.assertRaises(errors.Rejected):
            self.routines().check()


class BadReadTest(RoutinesCase):
    def test_a_failed_list_raises_so_nothing_is_decided_on_part_of_it(self) -> None:
        for failures in ([500], [None, 500]):
            with self.subTest(failures=failures):
                self.api.fail(*failures)
                with self.assertRaises(errors.Unavailable):
                    self.routines().plans()

    def test_a_chosen_folder_that_disappears_holds_its_workouts_and_is_logged_once(self) -> None:
        source = self.routines("Home", "42")
        source.plans()
        self.api.folders[1]["title"] = "Garage"
        with self.assertLogs("hevy_garmin_sync.routines", "ERROR") as logs:
            plans = source.plans()
        self.assertIn("'Home' in INCLUDE_HEVY_FOLDERS is gone", logs.output[0])
        self.assertTrue(plans.hold)
        self.assertEqual([w.name for w in plans.workouts], ["Hevy/Push Pull Legs: Push Day"])
        with self.assertNoLogs("hevy_garmin_sync.routines", "ERROR"):
            self.assertTrue(source.plans().hold)

    def test_it_is_logged_again_if_it_comes_back_and_goes_again(self) -> None:
        source = self.routines("Home")
        self.api.folders[1]["title"] = "Garage"
        with self.assertLogs("hevy_garmin_sync.routines", "ERROR"):
            source.plans()
        self.api.folders[1]["title"] = "Home"
        self.assertFalse(source.plans().hold)
        self.api.folders[1]["title"] = "Garage"
        with self.assertLogs("hevy_garmin_sync.routines", "ERROR"):
            source.plans()

    def test_a_routine_whose_folder_is_not_in_the_folder_list_is_left_alone(self) -> None:
        self.api.routines.append(hevy_routine("r-new", "Brand New", 77))
        plans = self.routines().plans()
        self.assertTrue(plans.hold)
        self.assertNotIn("r-new", [w.source_id for w in plans.workouts])

    def test_a_renamed_folder_chosen_by_id_renames_its_workouts(self) -> None:
        source = self.routines("42")
        self.api.folders[0]["title"] = "PPL"
        plans = source.plans()
        self.assertFalse(plans.hold)
        self.assertEqual([w.name for w in plans.workouts], ["Hevy/PPL: Push Day"])


class ConversionTest(RoutinesCase):
    def plan(self, *exercises: dict[str, Any]) -> workout.Workout:
        self.api.routines = [hevy_routine("r1", "Mixed", None, list(exercises))]
        (planned,) = self.routines().plans().workouts
        return planned

    def sets(self, *sets: dict[str, Any]) -> tuple[Set, ...]:
        return self.plan(hevy_exercise("T-BENCH", "Bench Press (Barbell)", list(sets))).exercises[0].sets

    def test_an_exercise_carries_its_garmin_name_title_rest_and_superset(self) -> None:
        planned = self.plan(
            hevy_exercise("T-BENCH", "Bench Press (Barbell)", [hevy_set(reps=8)], rest_seconds=90, superset_id=0),
            hevy_exercise("T-PLANK", "Plank", [hevy_set(duration_seconds=30)], rest_seconds=None, superset_id=0),
        )
        bench, plank = planned.exercises
        self.assertEqual(
            (bench.title, bench.category, bench.name), ("Bench Press (Barbell)", "BENCH_PRESS", "BARBELL_BENCH_PRESS")
        )
        self.assertEqual((bench.rest_seconds, bench.superset, bench.assisted), (90, 0, False))
        self.assertEqual((plank.rest_seconds, plank.superset), (None, 0))
        self.assertEqual(plank.sets, (Set(seconds=30),))

    def test_exercises_and_sets_follow_their_index_not_their_position(self) -> None:
        self.api.routines = [hevy_routine("r1", "Mixed")]
        first = hevy_exercise("T-BENCH", "Bench Press (Barbell)", [hevy_set(reps=8)])
        second = hevy_exercise("T-PLANK", "Plank", [hevy_set(reps=1), hevy_set(reps=2)])
        second["sets"].reverse()
        self.api.routines[0]["exercises"] = [second | {"index": 1}, first | {"index": 0}]
        (planned,) = self.routines().plans().workouts
        self.assertEqual([e.title for e in planned.exercises], ["Bench Press (Barbell)", "Plank"])
        self.assertEqual([s.reps for s in planned.exercises[1].sets], [1, 2])

    def test_a_set_reads_its_type_reps_weight_time_and_distance(self) -> None:
        self.assertEqual(
            self.sets(
                hevy_set(type="warmup", weight_kg=20),
                hevy_set(reps=8, weight_kg=60.5),
                hevy_set(type="dropset", reps=6.0),
                hevy_set(type="failure", rep_range={"start": 4, "end": 6}),
                hevy_set(duration_seconds=30, distance_meters=20),
            ),
            (
                Set(kind="warmup", weight_kg=20.0),
                Set(reps=8, weight_kg=60.5),
                Set(kind="dropset", reps=6),
                Set(kind="failure", rep_range=(4, 6)),
                Set(seconds=30, meters=20.0),
            ),
        )

    def test_half_a_rep_range_or_a_flat_one_is_a_plain_target(self) -> None:
        self.assertEqual(
            self.sets(
                hevy_set(rep_range={"start": 8, "end": None}),
                hevy_set(rep_range={"start": None, "end": 12}),
                hevy_set(rep_range={"start": 10, "end": 10}),
                hevy_set(reps=5, rep_range={"start": None, "end": None}),
            ),
            (Set(reps=8), Set(reps=12), Set(reps=10), Set(reps=5)),
        )

    def test_zero_and_junk_read_as_nothing(self) -> None:
        self.assertEqual(
            self.sets(
                hevy_set(reps=0, weight_kg=0, duration_seconds=0, distance_meters=0),
                hevy_set(type="mystery", reps="x", weight_kg=None),
            ),
            (Set(), Set()),
        )
        planned = self.plan(hevy_exercise("T-BENCH", "Bench", [hevy_set(reps=5)], rest_seconds=0, superset_id=True))
        self.assertEqual((planned.exercises[0].rest_seconds, planned.exercises[0].superset), (None, None))

    def test_an_assisted_exercise_is_known_by_its_template_type(self) -> None:
        self.api.templates.append(
            fixtures.hevy_template("T-ASSIST", "Pull Up (Assisted)", type="bodyweight_assisted_reps")
        )
        planned = self.plan(hevy_exercise("T-ASSIST", "Pull Up (Assisted)", [hevy_set(reps=8, weight_kg=20)]))
        self.assertTrue(planned.exercises[0].assisted)

    def test_a_custom_exercise_is_mapped_by_muscle_group_and_equipment(self) -> None:
        self.api.templates.append(
            fixtures.hevy_template(
                "T-MINE", "My Curl", is_custom=True, primary_muscle_group="biceps", equipment="dumbbell"
            )
        )
        planned = self.plan(hevy_exercise("T-MINE", "My Curl", [hevy_set(reps=8)]))
        self.assertEqual((planned.exercises[0].category, planned.exercises[0].name), ("CURL", "DUMBBELL_BICEPS_CURL"))

    def test_a_routine_with_no_exercises_is_still_planned_so_the_sync_can_say_why_it_is_skipped(self) -> None:
        self.api.routines = [hevy_routine("r1", "Empty", None, [])]
        (planned,) = self.routines().plans().workouts
        self.assertEqual(planned.exercises, ())


if __name__ == "__main__":
    unittest.main()
