"""Hevy Trainer's program as planned workouts: names, weights, what is read when (spec section 6, F-33)."""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hevy_garmin_sync import errors, hevy, trainer, workout
from hevy_garmin_sync.hevy_private import HevyPrivate
from hevy_garmin_sync.store import Store
from hevy_garmin_sync.workout import Exercise, Set
from tests import fixtures
from tests.fixtures import hevy_template, logged_set, logged_workout, trainer_exercise, trainer_template

LB = fixtures.LBS_PER_KG
LOGGER = "hevy_garmin_sync.trainer"
WEEK_8 = fixtures.PROGRAM_WEEK_8  # a Friday
TUESDAY = datetime(2026, 11, 3, 15, 13, tzinfo=fixtures.ZONE)  # the same week
INPUTS = ["v2/user_preferences", "hevy_trainer/user_preferences", "exercise_template_units", "user_workouts_paged"]


class TrainerCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name))
        self.public = fixtures.FakeHevyApi()
        self.public.templates += fixtures.trainer_exercise_templates()
        self.private = fixtures.FakeHevyPrivateApi()
        self.private.program = fixtures.trainer_program([fixtures.lower_template()])
        self.private.workouts = [fixtures.logged_lower(TUESDAY)]
        self.now = WEEK_8
        self.trainer = self.start()

    def start(self) -> trainer.Trainer:
        return trainer.Trainer(
            HevyPrivate(
                fixtures.HEVY_SESSION_TOKENS,
                self.store,
                self.private,  # type: ignore[arg-type]
                utcnow=lambda: self.now.astimezone(UTC),
            ),
            hevy.Hevy("made-up-key", self.public),  # type: ignore[arg-type]
            fixtures.exercise_map(),
            lambda: self.now,
        )

    def one(self, *exercises: dict[str, Any], **program: Any) -> None:
        """A program of one workout, 'Upper', holding these exercises."""
        template = trainer_template("t-upper", "upper_2x_a", list(exercises))
        self.private.program = fixtures.trainer_program([template], **program)

    def log(self, start: datetime, sets: dict[str, list[dict[str, Any]]], template_id: str = "t-upper") -> None:
        self.private.workouts.append(logged_workout(template_id, start, sets))

    def said(self) -> list[str]:
        """What a fresh start logs about each exercise, without the logger's prefix."""
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.start().plans()
        return [line.split("Hevy Trainer: ", 1)[1] for line in logs.output if "Hevy Trainer: " in line]

    def sets(self) -> tuple[Set, ...]:
        """The sets of the first exercise of the first workout."""
        return self.start().plans().workouts[0].exercises[0].sets


class NameTest(unittest.TestCase):
    def test_hevys_own_name_is_used_when_there_is_one(self) -> None:
        self.assertEqual(trainer.template_name({"name": "Upper Body", "key": "upper_2x_a"}), "Upper Body")

    def test_otherwise_the_name_is_the_keys_words_before_the_weekly_frequency(self) -> None:
        for key, name in (("lower_2x_a", "Lower"), ("full_body_3x_b", "Full Body"), ("push", "Push")):
            with self.subTest(key=key):
                self.assertEqual(trainer.template_name({"name": None, "key": key}), name)

    def test_a_key_with_no_words_is_used_as_it_is(self) -> None:
        self.assertEqual(trainer.template_name({"key": "3x_a"}), "3x_a")
        self.assertEqual(trainer.template_name({}), "Workout")

    def test_a_replys_shape_holds_its_keys_and_types_but_no_value(self) -> None:
        reply = {"units": [{"exercise_template_id": "T-BENCH", "weight_unit": "kg", "n": 1}], "empty": [], "at": None}
        self.assertEqual(
            trainer.shape(reply),
            {
                "units": [{"exercise_template_id": "str", "weight_unit": "str", "n": "int"}],
                "empty": [],
                "at": "NoneType",
            },
        )


class ProgramTest(TrainerCase):
    def test_a_logged_lower_gives_what_the_hevy_app_showed_next(self) -> None:
        with self.assertLogs(LOGGER, "INFO") as logs:
            plans = self.trainer.plans()
        (lower,) = plans.workouts
        self.assertEqual((lower.kind, lower.source_id), (workout.TRAINER, "t-lower"))
        self.assertEqual(lower.name, "Hevy/Trainer: Lower (C2-W2)")
        self.assertEqual(
            lower.exercises,
            (
                Exercise(
                    "Goblet Squat",
                    "SQUAT",
                    "GOBLET_SQUAT",
                    (
                        Set(kind="warmup", weight_kg=30 / LB),
                        Set(kind="warmup", weight_kg=50 / LB),
                        *[Set(rep_range=(4, 6), weight_kg=80 / LB)] * 3,
                    ),
                    rest_seconds=90,
                ),
                Exercise("Walking Lunge (Dumbbell)", "LUNGE", "DUMBBELL_LUNGE", (Set(rep_range=(10, 12)),) * 3, 90),
                Exercise(
                    "Lying Leg Raise", "LEG_RAISE", "LYING_STRAIGHT_LEG_RAISE", (Set(rep_range=(12, 15)),) * 3, 90
                ),
                Exercise(
                    "Side Bend (Dumbbell)", "CORE", "SIDE_BEND", (Set(rep_range=(10, 12), weight_kg=40 / LB),) * 3, 90
                ),
            ),
        )
        said = "\n".join(logs.output)
        self.assertIn("Hevy Trainer: Goblet Squat: 80 lbs (no change), warm-ups 30, 50", said)
        self.assertIn("Hevy Trainer: Lying Leg Raise: 12-15 reps (up)", said)
        self.assertIn("Hevy Trainer: Side Bend (Dumbbell): 40 lbs (up)", said)
        self.assertIn(
            "Walking Lunge (Dumbbell): no prescription (Trainer suggests no weight for a short_distance_weight "
            "exercise on dumbbell equipment)",
            said,
        )

    def test_the_plans_are_trainers_and_are_not_held(self) -> None:
        plans = self.trainer.plans()
        self.assertEqual((plans.kind, plans.hold), (workout.TRAINER, False))

    def test_the_name_carries_the_cycle_and_week_the_app_shows(self) -> None:
        cases = [
            (fixtures.PROGRAM_START, False, "(C1-W1)"),
            (WEEK_8, False, "(C2-W2)"),
            (WEEK_8, True, "(C2-W1)"),
            (datetime(2026, 10, 28, 9, 0, tzinfo=fixtures.ZONE), True, "(C1-W7)"),
        ]
        for now, deloads, label in cases:
            with self.subTest(now=now, deloads=deloads):
                self.now = now
                self.private.program = fixtures.trainer_program([fixtures.lower_template()], deloads_enabled=deloads)
                self.assertEqual(self.start().plans().workouts[0].name, f"Hevy/Trainer: Lower {label}")

    def test_the_week_turns_on_the_users_first_weekday(self) -> None:
        self.now = datetime(2026, 11, 8, 9, 0, tzinfo=fixtures.ZONE)  # a Sunday
        self.assertIn("(C2-W2)", self.start().plans().workouts[0].name)
        self.private.user["first_weekday"] = "sunday"
        self.assertIn("(C2-W3)", self.start().plans().workouts[0].name)

    def test_workouts_and_exercises_follow_their_index_and_a_template_with_no_id_is_left_out(self) -> None:
        upper = trainer_template(
            "t-upper", "upper_2x_a", [trainer_exercise("T-SIDE-BEND"), trainer_exercise("T-GOBLET")], name="Upper Body"
        )
        self.private.program = fixtures.trainer_program([fixtures.lower_template(), upper, {"key": "odd"}])
        self.private.program["templates"][0]["index"] = 5
        upper["exercises"][0]["index"] = 5
        plans = self.trainer.plans()
        self.assertEqual(
            [w.name for w in plans.workouts], ["Hevy/Trainer: Upper Body (C2-W2)", "Hevy/Trainer: Lower (C2-W2)"]
        )
        self.assertEqual([e.title for e in plans.workouts[0].exercises], ["Goblet Squat", "Side Bend (Dumbbell)"])

    def test_an_account_with_no_program_says_so_once_and_wants_no_trainer_workouts(self) -> None:
        self.private.program = None
        with self.assertLogs(LOGGER, "INFO") as logs:
            plans = self.trainer.plans()
        self.assertIn("no Hevy Trainer program; syncing routines only", logs.output[0])
        self.assertEqual((plans.kind, tuple(plans.workouts), plans.hold), (workout.TRAINER, (), False))
        with self.assertNoLogs(LOGGER, "INFO"):
            self.trainer.plans()
        self.assertEqual(self.private.paths(), ["hevy_trainer/v3/program"] * 2)

    def test_it_is_said_again_if_a_program_comes_and_goes(self) -> None:
        self.trainer.plans()
        self.private.program = None
        for _ in range(2):
            with self.assertLogs(LOGGER, "INFO"):
                self.trainer.plans()
            self.private.program = fixtures.trainer_program([])
            self.trainer.plans()
            self.private.program = None

    def test_the_startup_check_is_one_call_with_the_session(self) -> None:
        self.trainer.check()
        self.assertEqual(self.private.paths(), ["v2/user_preferences"])
        self.assertEqual(self.trainer.private_calls, 1)


class ReadingTest(TrainerCase):
    def poll(self) -> list[str]:
        self.private.requests.clear()
        self.trainer.plans()
        return self.private.paths()

    def test_the_first_poll_reads_the_program_the_preferences_and_the_logged_workouts(self) -> None:
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program", *INPUTS])

    def test_a_poll_after_that_reads_only_the_program_and_the_workout_events(self) -> None:
        self.poll()
        self.public.requests.clear()
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program"])
        self.assertEqual([path for path, _ in self.public.requests], ["/workouts/events"])

    def test_a_saved_edited_or_deleted_workout_has_everything_read_again(self) -> None:
        self.poll()
        self.public.events = [{"type": "updated", "workout": {"id": "made-up"}}]
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program", *INPUTS])
        self.public.events = []
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program"])

    def test_a_workout_event_is_not_lost_when_the_read_after_it_fails(self) -> None:
        self.poll()
        self.public.events = [{"type": "deleted", "id": "made-up"}]
        self.private.fail(503)
        with self.assertRaises(errors.Unavailable):
            self.trainer.plans()
        self.public.events = []
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program", *INPUTS])

    def test_local_midnight_has_everything_read_again(self) -> None:
        self.poll()
        self.now += timedelta(hours=5)
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program"])
        self.now += timedelta(hours=1, minutes=1)
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program", *INPUTS])

    def test_a_new_program_has_everything_read_again(self) -> None:
        self.poll()
        self.private.program = fixtures.trainer_program([fixtures.lower_template()], created_at="2026-11-02T09:00:00Z")
        self.assertEqual(self.poll(), ["hevy_trainer/v3/program", *INPUTS])

    def test_workout_events_are_asked_for_since_startup_and_then_since_the_poll_before(self) -> None:
        started = self.now
        self.now += timedelta(minutes=1)
        self.trainer.plans()
        self.now += timedelta(minutes=1)
        self.trainer.plans()
        asked = [params["since"] for path, params in self.public.requests if path == "/workouts/events"]
        self.assertEqual(asked, [hevy._utc(started), hevy._utc(started + timedelta(minutes=1))])

    def test_the_logged_workouts_are_read_from_the_programs_start(self) -> None:
        self.private.workouts.append(
            logged_workout("t-lower", fixtures.PROGRAM_START - timedelta(days=1), {"T-SIDE-BEND": [logged_set(5, 1)]})
        )
        self.poll()
        self.assertEqual(self.private.requests[-1][1], {"username": "someone", "limit": 3, "offset": 0})
        self.assertIn("Side Bend (Dumbbell): 40 lbs (up)", self.said())

    def test_the_shape_of_the_unit_overrides_reply_is_logged_once_with_no_values(self) -> None:
        self.private.units = [{"exercise_template_id": "T-SIDE-BEND", "weight_unit": "kg"}]
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.trainer.plans()
            self.now += timedelta(days=1)
            self.trainer.plans()
        shapes = [line for line in logs.output if "per-exercise units reply" in line]
        self.assertEqual(len(shapes), 1)
        self.assertIn("[{'exercise_template_id': 'str', 'weight_unit': 'str'}]", shapes[0])
        self.assertNotIn("T-SIDE-BEND'", shapes[0])

    def test_each_prescription_is_logged_when_first_worked_out_and_again_only_when_it_changes(self) -> None:
        self.trainer.plans()
        with self.assertNoLogs(LOGGER, "INFO"):
            self.trainer.plans()
        self.private.workouts.append(
            logged_workout("t-lower", TUESDAY + timedelta(days=2), {"T-SIDE-BEND": [logged_set(40, 12)] * 3})
        )
        self.public.events = [{"type": "updated", "workout": {"id": "made-up"}}]
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.trainer.plans()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Side Bend (Dumbbell): 45 lbs (up)", logs.output[0])


class CalendarTest(TrainerCase):
    def test_a_workout_logged_this_week_is_off_the_calendar(self) -> None:
        self.assertEqual(self.trainer.plans().off_calendar, frozenset({"t-lower"}))

    def test_one_logged_last_week_is_not(self) -> None:
        self.private.workouts = [fixtures.logged_lower(TUESDAY - timedelta(days=7))]
        self.assertEqual(self.trainer.plans().off_calendar, frozenset())

    def test_the_week_starts_on_the_users_first_weekday_in_the_users_zone(self) -> None:
        # 23:30 on Sunday 1 November in Los Angeles, which is already Monday in UTC.
        self.private.workouts = [fixtures.logged_lower(datetime(2026, 11, 1, 23, 30, tzinfo=fixtures.ZONE))]
        self.assertEqual(self.start().plans().off_calendar, frozenset())
        self.private.user["first_weekday"] = "sunday"
        self.assertEqual(self.start().plans().off_calendar, frozenset({"t-lower"}))

    def test_another_workouts_session_or_one_with_no_start_does_not_count(self) -> None:
        self.private.workouts = [
            logged_workout("t-upper", TUESDAY, {}),
            logged_workout(None, TUESDAY, {}),
            fixtures.logged_lower(TUESDAY) | {"start_time": None},
        ]
        self.assertEqual(self.trainer.plans().off_calendar, frozenset())
        self.assertIn("no prescription", self.said()[-1])


class WeightTest(TrainerCase):
    def setUp(self) -> None:
        super().setUp()
        self.private.workouts = []
        self.one(trainer_exercise("T-SIDE-BEND"))

    def test_the_weight_comes_from_this_workouts_latest_session(self) -> None:
        self.log(TUESDAY - timedelta(days=7), {"T-SIDE-BEND": [logged_set(20, 12)] * 3})
        self.log(TUESDAY, {"T-SIDE-BEND": [logged_set(35, 9)] * 3})
        self.log(TUESDAY + timedelta(days=1), {"T-SIDE-BEND": [logged_set(50, 12)] * 3}, "t-lower")
        self.log(TUESDAY + timedelta(days=2), {"T-GOBLET": [logged_set(80, 4)] * 3})
        self.assertEqual(self.said(), ["Side Bend (Dumbbell): 30 lbs (down)"])
        self.assertEqual(self.sets(), (Set(rep_range=(10, 12), weight_kg=30 / LB),) * 3)

    def test_an_exercise_logged_twice_in_one_session_counts_the_first_time(self) -> None:
        twice = logged_workout("t-upper", TUESDAY, {"T-SIDE-BEND": [logged_set(35, 12)] * 3})
        twice["exercises"].append({"exercise_template_id": "T-SIDE-BEND", "sets": [logged_set(10, 12)] * 3})
        self.private.workouts.append(twice)
        self.assertEqual(self.said(), ["Side Bend (Dumbbell): 40 lbs (up)"])

    def test_a_set_from_the_public_api_names_its_type_type(self) -> None:
        self.log(TUESDAY, {"T-SIDE-BEND": [{"type": "normal", "reps": 12, "weight_kg": 35 / LB}] * 3})
        self.assertEqual(self.said(), ["Side Bend (Dumbbell): 40 lbs (up)"])

    def test_a_deload_week_takes_sixty_percent_and_its_sessions_are_not_history(self) -> None:
        self.one(trainer_exercise("T-SIDE-BEND"), trainer_exercise("T-LEG-RAISE"), deloads_enabled=True)
        week_6 = datetime(2026, 10, 20, 17, 0, tzinfo=fixtures.ZONE)
        self.log(week_6, {"T-SIDE-BEND": [logged_set(35, 12)] * 3, "T-LEG-RAISE": [logged_set(None, 12)] * 3})
        self.now = week_6 + timedelta(days=8)
        self.assertEqual(
            self.said(), ["Side Bend (Dumbbell): 25 lbs (deload week)", "Lying Leg Raise: 8-12 reps (deload week)"]
        )
        self.log(self.now, {"T-SIDE-BEND": [logged_set(25, 12)] * 3, "T-LEG-RAISE": [logged_set(None, 12)] * 3})
        self.now = WEEK_8
        self.assertEqual(self.said(), ["Side Bend (Dumbbell): 40 lbs (up)", "Lying Leg Raise: 12-15 reps (up)"])

    def test_a_kilogram_account_is_rounded_to_its_kilogram_equipment(self) -> None:
        self.private.user["weight_unit"] = "kg"
        self.private.trainer = {"availableWeights": {"dumbbellsKg": [10, 10.5, 11]}}
        self.log(TUESDAY, {"T-SIDE-BEND": [{"indicator": "normal", "reps": 12, "weight_kg": 20}] * 3})
        self.assertEqual(self.said(), ["Side Bend (Dumbbell): 21 kg (up)"])
        self.assertEqual(self.sets()[0].weight_kg, 21)

    def test_with_no_equipment_listed_hevys_usual_weights_are_used(self) -> None:
        self.private.trainer = {}
        self.log(TUESDAY, {"T-SIDE-BEND": [logged_set(35, 12)] * 3})
        self.assertEqual(self.said(), ["Side Bend (Dumbbell): 40 lbs (up)"])

    def test_an_exercise_the_user_logs_in_the_other_unit_is_rounded_in_that_unit(self) -> None:
        self.log(TUESDAY, {"T-SIDE-BEND": [logged_set(35, 12)] * 3})
        understood = [
            [{"exercise_template_id": "T-SIDE-BEND", "weight_unit": "kg"}],
            {"exercise_template_units": [{"exercise_template_id": "T-SIDE-BEND", "unit": "kg"}]},
        ]
        not_understood: list[Any] = [
            {"T-SIDE-BEND": "kg"},
            None,
            ["T-SIDE-BEND", {"exercise_template_id": "T-SIDE-BEND", "weight_unit": "stone"}, {"weight_unit": "kg"}],
            [{"exercise_template_id": "T-GOBLET", "weight_unit": "kg"}],
        ]
        for reply in understood:
            with self.subTest(reply=reply):
                self.private.units = reply
                self.assertEqual(self.said()[-1], "Side Bend (Dumbbell): 20 kg (up)")
        for reply in not_understood:
            with self.subTest(reply=reply):
                self.private.units = reply
                self.assertEqual(self.said()[-1], "Side Bend (Dumbbell): 40 lbs (up)")

    def test_warm_ups_carry_a_weight_and_no_rep_target_and_a_third_one_has_neither(self) -> None:
        self.one(trainer_exercise("T-SIDE-BEND", warmups=3))
        self.log(TUESDAY, {"T-SIDE-BEND": [logged_set(40, 10)] * 3})
        self.assertEqual(
            self.sets()[:4],
            (
                Set(kind="warmup", weight_kg=15 / LB),
                Set(kind="warmup", weight_kg=25 / LB),
                Set(kind="warmup"),
                Set(rep_range=(10, 12), weight_kg=40 / LB),
            ),
        )

    def test_an_exercise_logged_by_reps_alone_moves_its_rep_range_instead(self) -> None:
        self.one(trainer_exercise("T-LEG-RAISE", warmups=1))
        self.assertEqual(self.said(), ["Lying Leg Raise: 10-12 reps (new exercise)"])
        self.log(TUESDAY, {"T-LEG-RAISE": [logged_set(None, 5)] * 3})
        self.assertEqual(self.said(), ["Lying Leg Raise: 8-12 reps (down)"])
        self.assertEqual(self.sets(), (Set(kind="warmup"), *[Set(rep_range=(8, 12))] * 3))

    def test_rest_is_the_programs_and_zero_is_none(self) -> None:
        self.one(trainer_exercise("T-SIDE-BEND", rest_seconds=0), trainer_exercise("T-GOBLET", rest_seconds=150))
        exercises = self.trainer.plans().workouts[0].exercises
        self.assertEqual([e.rest_seconds for e in exercises], [None, 150])


class NoPrescriptionTest(TrainerCase):
    def setUp(self) -> None:
        super().setUp()
        self.private.workouts = []
        self.public.templates += [
            hevy_template("T-SWING", "Kettlebell Swing", equipment="kettlebell"),
            hevy_template("T-DIP", "Dip (Weighted)", type="bodyweight_weighted", equipment="machine"),
            hevy_template("T-ASSIST", "Pull Up (Assisted)", type="bodyweight_assisted", equipment="machine"),
        ]

    def test_an_exercise_trainer_gives_no_weight_for_has_none_and_the_log_says_why(self) -> None:
        cases = [
            (
                trainer_exercise("T-SWING"),
                "Trainer suggests no weight for a weight_reps exercise on kettlebell equipment",
            ),
            (trainer_exercise("T-PLANK"), "Trainer suggests no weight for a duration exercise on none equipment"),
            (trainer_exercise("T-SIDE-BEND", kind="cardio"), "Trainer plans no weight or rep range for it"),
            (trainer_exercise("T-SIDE-BEND", rep_range=None), "Trainer plans no weight or rep range for it"),
            (trainer_exercise("T-DIP"), "it has not been logged in this workout yet"),
        ]
        for exercise, reason in cases:
            with self.subTest(reason=reason, exercise=exercise["exercise_template_id"]):
                self.one(exercise)
                self.private.workouts = [
                    logged_workout("t-upper", TUESDAY, {"T-SWING": [logged_set(35, 12)] * 3}),
                ]
                (said,) = self.said()
                self.assertEqual(said.split(": ", 1)[1], f"no prescription ({reason})")
                self.assertEqual({s.weight_kg for s in self.sets()}, {None})

    def test_a_last_session_with_no_working_set_gives_none(self) -> None:
        self.one(trainer_exercise("T-SIDE-BEND"))
        self.log(TUESDAY, {"T-SIDE-BEND": [logged_set(20, 12, "warmup")]})
        self.assertIn("its last session has no working set", self.said()[0])

    def test_a_weighted_bodyweight_exercise_gets_a_weight_once_it_is_logged(self) -> None:
        self.one(trainer_exercise("T-DIP"))
        self.log(TUESDAY, {"T-DIP": [logged_set(20, 12)] * 3})
        for spelling in hevy.WEIGHTED_BODYWEIGHT:
            with self.subTest(spelling):
                self.public.templates[-2]["type"] = spelling
                self.assertEqual(self.said(), ["Dip (Weighted): 25 lbs (up)"])

    def test_an_assisted_exercise_is_marked_assisted_and_gets_no_weight(self) -> None:
        self.one(trainer_exercise("T-ASSIST"))
        for spelling in hevy.ASSISTED:
            with self.subTest(spelling):
                self.public.templates[-1]["type"] = spelling
                (exercise,) = self.start().plans().workouts[0].exercises
                self.assertTrue(exercise.assisted)
                self.assertEqual(exercise.sets, (Set(rep_range=(10, 12)),) * 3)

    def test_with_no_rep_range_a_set_has_no_target_at_all(self) -> None:
        self.one(trainer_exercise("T-SIDE-BEND", rep_range=None, sets=2))
        self.assertEqual(self.sets(), (Set(), Set()))

    def test_an_exercise_hevy_has_no_template_for_is_still_planned(self) -> None:
        self.one(trainer_exercise("T-GONE"), trainer_exercise("T-GONE-2", title="Something New"))
        with self.assertLogs("hevy_garmin_sync", "INFO") as logs:
            first, second = self.trainer.plans().workouts[0].exercises
        self.assertEqual((first.title, first.category), ("T-GONE", "TOTAL_BODY"))
        self.assertEqual(second.title, "Something New")
        said = "\n".join(logs.output)
        self.assertIn("No exercise map row for Hevy exercise 'T-GONE'", said)
        self.assertIn("Trainer suggests no weight for a unknown exercise on unknown equipment", said)


class NewExerciseTest(TrainerCase):
    """An exercise this workout has never logged starts at a share of its best recent one-rep max (F-46)."""

    def setUp(self) -> None:
        super().setUp()
        self.private.workouts = []
        self.one(trainer_exercise("T-BENCH", warmups=1, rep_range=(4, 6)))

    def lifted(self, kilograms: float, reps: int, days_ago: int | None, set_type: str = "normal") -> dict[str, Any]:
        when = None if days_ago is None else (self.now - timedelta(days=days_ago)).astimezone(UTC).isoformat()
        return {"weight_kg": kilograms, "reps": reps, "set_type": set_type, "workout_start_time": when}

    def test_the_weight_is_a_share_of_the_best_one_rep_max_of_the_last_three_months(self) -> None:
        # 100 kg for 5 is a one-rep max of 100 / 0.89 kg; 80% of that is 198.17 lb, and the bar loads 200.
        self.public.history["T-BENCH"] = [self.lifted(100, 5, 30), self.lifted(90, 5, 10), self.lifted(140, 5, 200)]
        self.assertEqual(self.said(), ["Bench Press (Barbell): 200 lbs (new exercise), warm-ups 120"])
        self.assertEqual(
            self.sets(), (Set(kind="warmup", weight_kg=120 / LB), *[Set(rep_range=(4, 6), weight_kg=200 / LB)] * 3)
        )

    def test_with_nothing_in_three_months_the_last_twelve_count(self) -> None:
        self.public.history["T-BENCH"] = [self.lifted(140, 5, 200)]
        self.assertEqual(self.said(), ["Bench Press (Barbell): 275 lbs (new exercise), warm-ups 165"])

    def test_the_history_is_asked_for_once_for_the_last_twelve_months(self) -> None:
        self.public.history["T-BENCH"] = [self.lifted(100, 5, None)]
        self.assertEqual(self.said(), ["Bench Press (Barbell): 200 lbs (new exercise), warm-ups 120"])
        (asked,) = [params for path, params in self.public.requests if path == "/exercise_history/T-BENCH"]
        self.assertEqual(
            asked, {"start_date": hevy._utc(self.now - timedelta(days=365)), "end_date": hevy._utc(self.now)}
        )

    def test_it_is_kept_until_the_next_logged_workout(self) -> None:
        def asked() -> int:
            return sum(path == "/exercise_history/T-BENCH" for path, _ in self.public.requests)

        self.trainer.plans()
        self.trainer.plans()
        self.assertEqual(asked(), 1)
        self.public.events = [{"type": "updated", "workout": {"id": "made-up"}}]
        self.trainer.plans()
        self.assertEqual(asked(), 2)

    def test_warm_up_sets_and_sets_of_no_reps_are_no_one_rep_max(self) -> None:
        self.public.history["T-BENCH"] = [self.lifted(200, 5, 10, "warmup"), self.lifted(100, 0, 10)]
        (said,) = self.said()
        self.assertTrue(said.endswith("(it is new to this workout and nothing gives it a starting weight)"), said)
        self.assertEqual(self.sets(), (Set(kind="warmup"), *[Set(rep_range=(4, 6))] * 3))

    def test_a_rep_range_trainer_has_no_share_for_gets_no_weight(self) -> None:
        self.one(trainer_exercise("T-BENCH", rep_range=(15, 20)))
        self.public.history["T-BENCH"] = [self.lifted(100, 5, 30)]
        self.assertIn("nothing gives it a starting weight", self.said()[0])

    def test_once_the_exercise_is_logged_in_this_workout_its_history_is_not_asked_for(self) -> None:
        self.log(TUESDAY, {"T-BENCH": [logged_set(135, 6)] * 3})
        # 5% over 135 lb is 141.75, and the nearest step up from 135 that the bar loads is 140.
        self.assertEqual(self.said(), ["Bench Press (Barbell): 140 lbs (up), warm-ups 85"])
        self.assertNotIn("/exercise_history/T-BENCH", [path for path, _ in self.public.requests])


if __name__ == "__main__":
    unittest.main()
