"""What the status page shows, built from what the loop knows (spec W-2)."""

import json
import unittest
from datetime import timedelta

from hevy_garmin_sync import status
from hevy_garmin_sync.sync import Counts, Report
from hevy_garmin_sync.workout import ROUTINE, STATUTE_US, TRAINER, Exercise, LoggedSet, Set, Workout
from tests import fixtures

KG = 1 / 2.2046226218  # one pound, in kilograms


def exercise(*sets: Set, **fields: object) -> Exercise:
    return Exercise("Squat (Barbell)", "SQUAT", "BARBELL_BACK_SQUAT", tuple(sets), **fields)  # type: ignore[arg-type]


def facts(*reports: Report, system: str | None = STATUTE_US, **fields: object) -> status.Facts:
    given: dict[str, object] = {
        "version": "1.2.3",
        "zone": "America/Los_Angeles",
        "started": fixtures.NOW - timedelta(hours=3),
        "poll_seconds": 60,
        "next_auto_sync": fixtures.NOW + timedelta(seconds=60),
        "last_daily_run": fixtures.NOW - timedelta(hours=1),
        "last_counts": Counts(created=1),
        "next_daily_run": fixtures.NOW + timedelta(hours=6),
        "services": (
            status.Service("Hevy", "working"),
            status.Service("Garmin", "waiting", "rate limited", fixtures.NOW),
        ),
        "run": status.Run(),
        "last_manual": None,
        "last_manual_counts": None,
        "reports": reports,
        "system": system,
        "settings": {"HEVY_API_KEY": "set"},
    }
    return status.Facts(**(given | fields))  # type: ignore[arg-type]


class BuildTest(unittest.TestCase):
    def test_the_app_its_services_and_its_run_are_shown_with_times_in_iso_form(self) -> None:
        built = status.build(facts(run=status.Run("running", True, "Writing workouts", 2, 8)))
        self.assertEqual(built["version"], "1.2.3")
        self.assertEqual(built["time_zone"], "America/Los_Angeles")
        self.assertEqual(built["next_daily_run"], (fixtures.NOW + timedelta(hours=6)).isoformat())
        self.assertEqual(built["last_counts"]["created"], 1)
        self.assertEqual(built["services"][1], {"name": "Garmin", "state": "waiting", "reason": "rate limited",
                                                "next_try": fixtures.NOW.isoformat()})
        self.assertEqual(
            built["sync"],
            {"state": "running", "force": True, "step": "Writing workouts", "done": 2, "total": 8, "starts": None,
             "last_ended": None, "last_counts": None},
        )
        self.assertEqual(built["settings"], {"HEVY_API_KEY": "set"})
        json.dumps(built)  # every value is JSON

    def test_a_routine_carries_its_hevy_id_for_the_link_and_a_trainer_workout_none(self) -> None:
        routine = Workout(ROUTINE, "r-1", "Hevy/PPL: Push", (), title="Push", folder="PPL")
        trainer = Workout(TRAINER, "t-1", "Hevy/Trainer: Upper (C1-W2)", (), title="Upper (C1-W2)")
        reports = Report(routine, 101, fixtures.TODAY, fixtures.NOW), Report(trainer, None, None, None)
        push, upper = status.build(facts(*reports))["workouts"]
        self.assertEqual(
            (push["title"], push["folder"], push["hevy_id"], push["garmin_id"]), ("Push", "PPL", "r-1", 101)
        )
        self.assertEqual((push["scheduled"], push["synced"]), (fixtures.TODAY.isoformat(), fixtures.NOW.isoformat()))
        self.assertEqual((upper["hevy_id"], upper["garmin_id"], upper["scheduled"]), (None, None, None))

    def test_a_refused_workout_carries_garmins_reason_and_the_next_try(self) -> None:
        plan = Workout(ROUTINE, "r-1", "Hevy: Legs", ())
        built = status.build(facts(Report(plan, None, None, None, "Invalid step", fixtures.NOW)))
        self.assertEqual(built["workouts"][0]["title"], "Hevy: Legs")  # no title of its own: the Garmin name
        self.assertEqual((built["workouts"][0]["refused"], built["workouts"][0]["retry"]),
                         ("Invalid step", fixtures.NOW.isoformat()))

    def test_an_exercise_shows_its_garmin_name_what_chose_it_and_trainers_numbers(self) -> None:
        squat = exercise(
            Set("warmup", weight_kg=95 * KG),
            Set("warmup", weight_kg=135 * KG),
            *[Set(reps=5, weight_kg=185 * KG)] * 3,
            rest_seconds=180,
            chosen_by="guess",
            direction="up",
            previous=(LoggedSet(180 * KG, 5),) * 3,
        )
        built = status.build(facts(Report(Workout(TRAINER, "t", "n", (squat,)), 1, None, None)))
        self.assertEqual(
            built["workouts"][0]["exercises"][0],
            {"hevy": "Squat (Barbell)", "garmin": "Barbell Back Squat", "chosen_by": "guess", "sets": "3 × 5",
             "rest": "Rest 3 min", "last": "Last 3 × 5 @ 180", "weight": "185 lb", "direction": "up",
             "warmups": "95, 135", "no_weight": None},
        )

    def test_weights_show_in_the_unit_garmin_got_them_in_and_a_spread_as_a_range(self) -> None:
        sets = (Set(reps=8, weight_kg=60), Set(reps=8, weight_kg=70), Set(reps=8, weight_kg=65))
        plan = Workout(ROUTINE, "r", "n", (exercise(*sets), exercise(Set(reps=8))))
        loaded, bare = status.build(facts(Report(plan, 1, None, None), system="metric"))["workouts"][0]["exercises"]
        self.assertEqual(loaded["weight"], "60–70 kg")
        self.assertIsNone(bare["weight"])
        self.assertIsNone(bare["warmups"])


class TextTest(unittest.TestCase):
    def test_sets(self) -> None:
        cases = {
            (Set(reps=5),) * 3: "3 × 5",
            (Set(rep_range=(8, 12)),) * 3: "3 × 8–12",
            (Set(seconds=45),) * 2: "2 × 45 s",
            (Set(seconds=90),): "1 × 1 min 30 s",
            (Set(meters=500),): "1 × 500 m",
            (Set(),) * 3: "3 sets",
            (Set(reps=5), Set(reps=5), Set(reps=3)): "5, 5, 3",
            (Set(reps=5), Set()): "5, ?",
            (Set("warmup"),): None,
        }
        for sets, text in cases.items():
            with self.subTest(text=text):
                self.assertEqual(status.sets_text(exercise(*sets)), text)

    def test_rest(self) -> None:
        self.assertEqual(status.rest_text(90), "Rest 1 min 30 s")
        self.assertEqual(status.rest_text(60), "Rest 1 min")
        self.assertEqual(status.rest_text(45), "Rest 45 s")
        self.assertIsNone(status.rest_text(None))

    def test_last_times_sets_fold_up_what_repeats(self) -> None:
        lb = 1 / 2.2046226218
        cases = {
            (LoggedSet(110 * lb, 12), LoggedSet(110 * lb, 11), LoggedSet(110 * lb, 10)): "Last 12, 11, 10 @ 110",
            (LoggedSet(180 * lb, 5), LoggedSet(185 * lb, 3)): "Last 180 × 5, 185 × 3",
            (LoggedSet(None, 12),) * 2: "Last 2 × 12",
            (LoggedSet(None, seconds=60), LoggedSet(20 * lb, meters=400)): "Last 1 min, 20 × 400 m",
            (LoggedSet(),): None,
            (): None,
        }
        for logged, text in cases.items():
            with self.subTest(text=text):
                self.assertEqual(status.last_text(logged, "lb"), text)

    def test_garmins_key_reads_as_words(self) -> None:
        self.assertEqual(status.garmin_name("SQUAT", "BARBELL_BACK_SQUAT"), "Barbell Back Squat")
        self.assertEqual(status.garmin_name("CURL", ""), "Curl")


if __name__ == "__main__":
    unittest.main()
