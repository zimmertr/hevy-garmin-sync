"""A planned workout becomes the Garmin steps the spec's watch checks proved (sections 3 and 4)."""

import unittest
from typing import Any

from hevy_garmin_sync import workout
from hevy_garmin_sync.workout import Exercise, LoggedSet, Owner, Set, Workout
from tests import fixtures

LAP_BUTTON = {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}
TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
REPS = {"conditionTypeId": 10, "conditionTypeKey": "reps", "displayOrder": 10, "displayable": True}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
KG_40_LB = 18.1437
LB = 2.2046226218  # pounds in a kilogram


def side_bend(*sets: Set, **kwargs: Any) -> Exercise:
    return Exercise("Side Bend", "CORE", "SIDE_BEND", sets, **{"rest_seconds": 30} | kwargs)


def crunch(*sets: Set, **kwargs: Any) -> Exercise:
    return Exercise("Crunch", "CRUNCH", "CRUNCH", sets, **{"rest_seconds": 60} | kwargs)


def plank(*sets: Set, **kwargs: Any) -> Exercise:
    return Exercise("Plank", "PLANK", "PLANK", sets, **{"rest_seconds": 30} | kwargs)


def routine(*exercises: Exercise, name: str = "Hevy: Core") -> Workout:
    return Workout(workout.ROUTINE, "routine-1", name, exercises)


def steps(*exercises: Exercise, system: str | None = "statute_us") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = workout.build(routine(*exercises), system)["workoutSegments"][0]["workoutSteps"]
    return found


def kinds(found: list[dict[str, Any]]) -> list[str]:
    """One word per step: the exercise, `rest`, `open` (a rest ending on a press) or `repeat`."""
    words = []
    for step in found:
        if "workoutSteps" in step:
            words.append(f"repeat{step['numberOfIterations']}({' '.join(kinds(step['workoutSteps']))})")
        elif step["stepType"]["stepTypeKey"] == "rest":
            words.append("open" if step["endCondition"] == LAP_BUTTON else f"rest{int(step['endConditionValue'])}")
        else:
            words.append(step["exerciseName"])
    return words


class SetStepTest(unittest.TestCase):
    def test_a_set_and_its_rest_are_what_the_fenix_8_was_sent(self) -> None:
        body = workout.build(routine(side_bend(Set(reps=12, weight_kg=KG_40_LB))), "statute_us")
        self.assertEqual(
            body,
            {
                "workoutName": "Hevy: Core",
                "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
                "estimatedDurationInSecs": 0,
                "author": {},
                "workoutSegments": [
                    {
                        "segmentOrder": 1,
                        "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
                        "workoutSteps": [
                            {
                                "type": "ExecutableStepDTO",
                                "stepOrder": 1,
                                "stepType": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
                                "endCondition": REPS,
                                "endConditionValue": 12.0,
                                "targetType": NO_TARGET,
                                "category": "CORE",
                                "exerciseName": "SIDE_BEND",
                                "weightValue": 40.0,
                                "weightUnit": {"unitId": 7, "unitKey": "pound"},
                            },
                            {
                                "type": "ExecutableStepDTO",
                                "stepOrder": 2,
                                "stepType": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
                                "endCondition": TIME,
                                "endConditionValue": 30.0,
                                "targetType": NO_TARGET,
                            },
                        ],
                    }
                ],
            },
        )

    def test_pounds_keep_two_decimals_so_half_pound_plates_survive(self) -> None:
        (step, _) = steps(side_bend(Set(reps=5, weight_kg=7.93787)))
        self.assertEqual(step["weightValue"], 17.5)

    def test_a_metric_profile_gets_kilograms_as_they_are(self) -> None:
        for system in ("metric", "statute_uk", None):
            with self.subTest(system=system):
                (step, _) = steps(side_bend(Set(reps=5, weight_kg=22.5)), system=system)
                self.assertEqual(step["weightValue"], 22.5)
                self.assertEqual(step["weightUnit"], {"unitId": 8, "unitKey": "kilogram"})

    def test_no_weight_or_zero_weight_sends_no_weight_target(self) -> None:
        for weight in (None, 0, 0.0):
            with self.subTest(weight=weight):
                (step, _) = steps(side_bend(Set(reps=5, weight_kg=weight)))
                self.assertNotIn("weightValue", step)
                self.assertNotIn("weightUnit", step)

    def test_a_rep_range_targets_its_top_and_puts_the_range_in_the_note(self) -> None:
        (step, _) = steps(side_bend(Set(rep_range=(4, 6))))
        self.assertEqual((step["endCondition"], step["endConditionValue"]), (REPS, 6.0))
        self.assertEqual(step["description"], "4-6 reps")

    def test_a_set_with_no_rep_target_ends_on_a_button_press_and_keeps_its_weight(self) -> None:
        (step, _) = steps(side_bend(Set(kind="warmup", weight_kg=KG_40_LB)))
        self.assertEqual(step["endCondition"], LAP_BUTTON)
        self.assertIsNone(step["endConditionValue"])
        self.assertEqual(step["weightValue"], 40.0)

    def test_a_warm_up_is_marked_and_noted(self) -> None:
        (step, _) = steps(side_bend(Set(kind="warmup", reps=10)))
        self.assertEqual(step["stepType"], {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1})
        self.assertEqual(step["description"], "Warm-up")

    def test_each_set_carries_the_one_note_the_spec_lists(self) -> None:
        cases: list[tuple[Set, bool, str | None]] = [
            (Set(reps=8), False, None),
            (Set(rep_range=(8, 8)), False, None),
            (Set(rep_range=(4, 6)), False, "4-6 reps"),
            (Set(kind="warmup"), False, "Warm-up"),
            (Set(kind="warmup", rep_range=(8, 10)), False, "Warm-up: 8-10 reps"),
            (Set(kind="dropset", rep_range=(4, 6)), False, "Drop set: 4-6 reps"),
            (Set(kind="dropset", reps=6), False, "Drop set"),
            (Set(kind="failure", rep_range=(4, 6)), False, "To failure: 4-6 reps"),
            (Set(kind="failure", reps=6), False, "To failure"),
            (Set(reps=8), True, "Assisted"),
            (Set(rep_range=(4, 6)), True, "Assisted: 4-6 reps"),
            (Set(kind="warmup", rep_range=(8, 10)), True, "Warm-up, assisted: 8-10 reps"),
            (Set(kind="dropset", reps=6), True, "Drop set, assisted"),
            (Set(meters=20), False, "22 yd"),
            (Set(kind="warmup", meters=20), False, "Warm-up: 22 yd"),
            (Set(kind="dropset", meters=20), False, "Drop set: 22 yd"),
        ]
        for planned, assisted, note in cases:
            with self.subTest(set=planned, assisted=assisted):
                (step, _) = steps(side_bend(planned, assisted=assisted))
                self.assertEqual(step.get("description"), note)

    def test_a_drop_set_and_a_set_to_failure_are_normal_steps(self) -> None:
        for kind in ("dropset", "failure"):
            with self.subTest(kind=kind):
                (step, _) = steps(side_bend(Set(kind=kind, reps=6)))
                self.assertEqual(step["stepType"]["stepTypeKey"], "interval")


class RestTest(unittest.TestCase):
    def test_every_set_is_followed_by_a_rest_the_last_included(self) -> None:
        found = steps(side_bend(Set(reps=12), Set(reps=10)), crunch(Set(reps=15)))
        self.assertEqual(kinds(found), ["SIDE_BEND", "rest30", "SIDE_BEND", "rest30", "CRUNCH", "rest60"])

    def test_no_rest_timer_becomes_a_rest_that_waits_for_a_press(self) -> None:
        for rest in (None, 0):
            with self.subTest(rest=rest):
                (_, rest_step) = steps(side_bend(Set(reps=12), rest_seconds=rest))
                self.assertEqual(rest_step["stepType"]["stepTypeKey"], "rest")
                self.assertEqual(rest_step["endCondition"], LAP_BUTTON)
                self.assertIsNone(rest_step["endConditionValue"])


class RepeatGroupTest(unittest.TestCase):
    def test_matching_sets_share_one_repeat_group(self) -> None:
        (group,) = steps(side_bend(*[Set(reps=12, weight_kg=KG_40_LB)] * 3))
        children = group.pop("workoutSteps")
        self.assertEqual(
            group,
            {
                "type": "RepeatGroupDTO",
                "stepOrder": 1,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                "numberOfIterations": 3,
                "endCondition": {
                    "conditionTypeId": 7,
                    "conditionTypeKey": "iterations",
                    "displayOrder": 7,
                    "displayable": False,
                },
                "endConditionValue": 3.0,
                "childStepId": 1,
                "smartRepeat": False,
                "skipLastRestStep": False,
            },
        )
        self.assertEqual(kinds(children), ["SIDE_BEND", "rest30"])
        self.assertEqual([(c["stepOrder"], c["childStepId"]) for c in children], [(2, 1), (3, 1)])

    def test_a_warm_up_and_a_heavier_top_set_stay_outside_the_group(self) -> None:
        found = steps(
            side_bend(
                Set(kind="warmup", reps=12, weight_kg=9.07185),
                *[Set(reps=12, weight_kg=KG_40_LB)] * 3,
                Set(reps=8, weight_kg=20.4117),
            )
        )
        self.assertEqual(kinds(found), ["SIDE_BEND", "rest30", "repeat3(SIDE_BEND rest30)", "SIDE_BEND", "rest30"])
        self.assertEqual([s["stepOrder"] for s in found], [1, 2, 3, 6, 7])
        self.assertEqual([c["stepOrder"] for c in found[2]["workoutSteps"]], [4, 5])
        self.assertNotIn("childStepId", found[0])

    def test_sets_that_differ_in_anything_do_not_group(self) -> None:
        base = Set(reps=12, weight_kg=KG_40_LB)
        for other in (
            Set(reps=10, weight_kg=KG_40_LB),
            Set(reps=12, weight_kg=20.0),
            Set(kind="dropset", reps=12, weight_kg=KG_40_LB),
            Set(rep_range=(10, 12), weight_kg=KG_40_LB),
        ):
            with self.subTest(other=other):
                self.assertEqual(kinds(steps(side_bend(base, other))), ["SIDE_BEND", "rest30"] * 2)

    def test_each_group_gets_its_own_child_step_id(self) -> None:
        found = steps(side_bend(*[Set(reps=12)] * 2), crunch(*[Set(reps=15)] * 3))
        self.assertEqual([g["childStepId"] for g in found], [1, 2])
        self.assertEqual([c["childStepId"] for g in found for c in g["workoutSteps"]], [1, 1, 2, 2])
        self.assertEqual([g["stepOrder"] for g in found], [1, 4])

    def test_the_same_sets_of_two_exercises_never_merge(self) -> None:
        found = steps(side_bend(Set(reps=12)), side_bend(Set(reps=12)))
        self.assertEqual(kinds(found), ["SIDE_BEND", "rest30", "SIDE_BEND", "rest30"])


class SupersetTest(unittest.TestCase):
    def test_rounds_alternate_with_an_open_rest_between_the_exercises(self) -> None:
        found = steps(
            side_bend(*[Set(reps=12, weight_kg=KG_40_LB)] * 2, superset=0),
            crunch(*[Set(reps=15)] * 2, superset=0),
        )
        self.assertEqual(kinds(found), ["repeat2(SIDE_BEND open CRUNCH rest60)"])

    def test_a_round_that_differs_gets_its_own_steps(self) -> None:
        found = steps(
            side_bend(Set(reps=12), Set(reps=12), Set(reps=8), superset=0),
            crunch(*[Set(reps=15)] * 3, superset=0),
        )
        self.assertEqual(
            kinds(found), ["repeat2(SIDE_BEND open CRUNCH rest60)", "SIDE_BEND", "open", "CRUNCH", "rest60"]
        )

    def test_three_exercises_rest_on_a_timer_only_after_the_last(self) -> None:
        found = steps(
            side_bend(Set(reps=12), superset=4),
            crunch(Set(reps=15), superset=4),
            plank(Set(reps=5), superset=4, rest_seconds=90),
        )
        self.assertEqual(kinds(found), ["SIDE_BEND", "open", "CRUNCH", "open", "PLANK", "rest90"])

    def test_a_later_round_holds_only_the_exercises_that_still_have_a_set(self) -> None:
        found = steps(side_bend(*[Set(reps=12)] * 3, superset=0), crunch(Set(reps=15), superset=0))
        self.assertEqual(kinds(found), ["SIDE_BEND", "open", "CRUNCH", "rest60", "repeat2(SIDE_BEND rest30)"])

    def test_the_round_rests_openly_when_its_last_exercise_has_no_timer(self) -> None:
        found = steps(side_bend(Set(reps=12), superset=0), crunch(Set(reps=15), superset=0, rest_seconds=None))
        self.assertEqual(kinds(found), ["SIDE_BEND", "open", "CRUNCH", "open"])

    def test_a_split_superset_sits_where_its_first_exercise_is(self) -> None:
        found = steps(
            side_bend(Set(reps=12), superset=0),
            plank(Set(reps=5)),
            crunch(Set(reps=15), superset=0),
        )
        self.assertEqual(kinds(found), ["SIDE_BEND", "open", "CRUNCH", "rest60", "PLANK", "rest30"])

    def test_two_supersets_stay_apart(self) -> None:
        found = steps(
            side_bend(Set(reps=12), superset=0),
            crunch(Set(reps=15), superset=0),
            plank(Set(reps=5), superset=1),
            side_bend(Set(reps=9), superset=1),
        )
        self.assertEqual(
            kinds(found), ["SIDE_BEND", "open", "CRUNCH", "rest60", "PLANK", "open", "SIDE_BEND", "rest30"]
        )


class TimeAndDistanceTest(unittest.TestCase):
    def test_a_timed_set_waits_for_a_press_then_counts_down(self) -> None:
        (wait, timed, rest) = steps(plank(Set(seconds=30)))
        self.assertEqual(wait["stepType"]["stepTypeKey"], "rest")
        self.assertEqual(wait["endCondition"], LAP_BUTTON)
        self.assertEqual(wait["description"], "Press Lap button to start 30s Plank countdown")
        self.assertEqual((timed["endCondition"], timed["endConditionValue"]), (TIME, 30.0))
        self.assertEqual(kinds([rest]), ["rest30"])

    def test_the_wait_step_spells_minutes_and_seconds(self) -> None:
        for seconds, spelled in ((45, "45s"), (60, "1m"), (90, "1m 30s")):
            with self.subTest(seconds=seconds):
                (wait, _, _) = steps(plank(Set(seconds=seconds)))
                self.assertEqual(wait["description"], f"Press Lap button to start {spelled} Plank countdown")

    def test_the_wait_step_is_inside_the_repeat_group(self) -> None:
        self.assertEqual(kinds(steps(plank(*[Set(seconds=30)] * 3))), ["repeat3(open PLANK rest30)"])

    def test_a_timed_set_keeps_its_weight(self) -> None:
        (_, timed, _) = steps(plank(Set(seconds=30, weight_kg=KG_40_LB)))
        self.assertEqual(timed["weightValue"], 40.0)

    def test_a_distance_ends_on_a_press_with_the_distance_in_the_note(self) -> None:
        carry = Exercise("Farmer's Walk", "CARRY", "FARMERS_WALK", (Set(meters=20, weight_kg=22.6796),), 30)
        for system, note in (("statute_us", "22 yd"), ("statute_uk", "22 yd"), ("metric", "20 m"), (None, "20 m")):
            with self.subTest(system=system):
                (step, _) = steps(carry, system=system)
                self.assertEqual(step["endCondition"], LAP_BUTTON)
                self.assertIsNone(step["endConditionValue"])
                self.assertEqual(step["description"], note)
                self.assertIn("weightValue", step)

    def test_a_timed_carry_counts_down_and_notes_its_distance(self) -> None:
        carry = Exercise("Farmer's Walk", "CARRY", "FARMERS_WALK", (Set(seconds=45, meters=20),), 30)
        (wait, step, _) = steps(carry)
        self.assertEqual(wait["description"], "Press Lap button to start 45s Farmer's Walk countdown")
        self.assertEqual((step["endCondition"], step["endConditionValue"]), (TIME, 45.0))
        self.assertEqual(step["description"], "22 yd")


class PreviousTest(unittest.TestCase):
    """Last time's working sets, one to a line, after the note every set but a warm-up carries (F-30, #3)."""

    def note(self, *logged: LoggedSet, planned: Set | None = None, system: str | None = "statute_us") -> str | None:
        (step, _) = steps(side_bend(planned or Set(reps=6), previous=logged), system=system)
        found: str | None = step.get("description")
        return found

    def test_the_block_follows_the_sets_own_note_and_names_the_unit_once(self) -> None:
        last = (LoggedSet(65 / LB, 6, 7), LoggedSet(65 / LB, 6, 7.5), LoggedSet(65 / LB, 5, 8))
        note = self.note(*last, planned=Set(rep_range=(4, 6)))
        self.assertEqual(note, "4-6 reps\nPrev (lb):\n65 x 6 @ 7\n65 x 6 @ 7.5\n65 x 5 @ 8")

    def test_it_is_the_whole_note_when_the_set_has_none(self) -> None:
        self.assertEqual(self.note(LoggedSet(20, 8)), "Prev (lb):\n44.1 x 8")

    def test_the_unit_is_the_one_the_weights_go_to_garmin_in(self) -> None:
        for system in ("metric", "statute_uk", None):
            with self.subTest(system=system):
                note = self.note(LoggedSet(80.0, 5), LoggedSet(102.5, 3), system=system)
                self.assertEqual(note, "Prev (kg):\n80 x 5\n102.5 x 3")

    def test_a_set_with_no_weight_is_its_amount_and_the_heading_names_no_unit(self) -> None:
        self.assertEqual(self.note(LoggedSet(reps=20, rpe=7.5), LoggedSet(reps=18)), "Prev:\n20 @ 7.5\n18")

    def test_a_weight_with_no_amount_is_the_weight_alone(self) -> None:
        self.assertEqual(self.note(LoggedSet(20, rpe=8), system="metric"), "Prev (kg):\n20 @ 8")

    def test_a_time_is_spelled_as_the_countdown_is_and_a_distance_as_the_set_note_is(self) -> None:
        last = (LoggedSet(seconds=45), LoggedSet(seconds=90, rpe=9), LoggedSet(20, meters=25))
        self.assertEqual(self.note(*last, system="metric"), "Prev (kg):\n45s\n1m 30s @ 9\n20 x 25 m")
        self.assertEqual(self.note(LoggedSet(meters=25), system="statute_uk"), "Prev:\n27 yd")

    def test_reps_are_shown_before_a_time_and_a_time_before_a_distance(self) -> None:
        last = (LoggedSet(reps=10, seconds=30, meters=20), LoggedSet(seconds=30, meters=20))
        self.assertEqual(self.note(*last, system="metric"), "Prev:\n10\n30s")

    def test_a_line_of_more_than_eight_digits_drops_the_spaces_after_x_and_at(self) -> None:
        cases = [
            (LoggedSet(102.5, 12, 9.5), "Prev (kg):\n102.5 x 12 @ 9.5"),
            (LoggedSet(1002.5, 12, 9.5), "Prev (kg):\n1002.5 x12 @9.5"),
            (LoggedSet(1002.5, 1000), "Prev (kg):\n1002.5 x1000"),
            (LoggedSet(reps=123456789, rpe=8), "Prev:\n123456789 @8"),
        ]
        for logged, note in cases:
            with self.subTest(note=note):
                self.assertEqual(self.note(logged, system="metric"), note)

    def test_a_set_logged_with_nothing_in_it_is_left_out(self) -> None:
        self.assertEqual(self.note(LoggedSet(), LoggedSet(rpe=8), LoggedSet(reps=5)), "Prev:\n5")
        self.assertIsNone(self.note(LoggedSet(rpe=8)))
        self.assertIsNone(self.note())

    def test_a_warm_up_keeps_its_own_note_and_every_other_set_gets_the_block(self) -> None:
        found = steps(
            side_bend(Set(kind="warmup", reps=10), Set(kind="dropset", reps=6), previous=(LoggedSet(reps=12),))
        )
        self.assertEqual([s.get("description") for s in found], ["Warm-up", None, "Drop set\nPrev:\n12", None])

    def test_matching_sets_still_share_one_repeat_group(self) -> None:
        last = (LoggedSet(20, 12, 8), LoggedSet(20, 10, 9))
        found = steps(side_bend(Set(kind="warmup", reps=12), *[Set(reps=12, weight_kg=KG_40_LB)] * 3, previous=last))
        self.assertEqual(kinds(found), ["SIDE_BEND", "rest30", "repeat3(SIDE_BEND rest30)"])
        self.assertEqual(found[2]["workoutSteps"][0]["description"], "Prev (lb):\n44.1 x 12 @ 8\n44.1 x 10 @ 9")

    def test_the_version_changes_with_last_times_sets_and_only_with_them(self) -> None:
        def version(*logged: LoggedSet) -> str:
            return workout.version(workout.build(routine(side_bend(Set(reps=12), previous=logged)), "statute_us"))

        self.assertEqual(version(LoggedSet(20, 12)), version(LoggedSet(20, 12)))
        self.assertNotEqual(version(LoggedSet(20, 12)), version(LoggedSet(20, 11)))
        self.assertNotEqual(version(LoggedSet(20, 12)), version())


class OrderTest(unittest.TestCase):
    def test_exercises_keep_their_order_and_an_empty_one_adds_nothing(self) -> None:
        found = steps(crunch(Set(reps=15)), side_bend(), plank(Set(reps=5)))
        self.assertEqual(kinds(found), ["CRUNCH", "rest60", "PLANK", "rest30"])

    def test_a_workout_with_no_sets_has_no_steps(self) -> None:
        self.assertEqual(steps(side_bend()), [])
        self.assertEqual(steps(), [])

    def test_step_count_includes_groups_and_what_is_inside_them(self) -> None:
        body = workout.build(routine(side_bend(Set(kind="warmup"), *[Set(reps=12)] * 3)), "statute_us")
        self.assertEqual(workout.step_count(body), 5)


class OwnershipTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = routine(side_bend(Set(reps=12)))
        self.body = workout.build(self.plan, "statute_us")

    def test_the_description_is_the_four_lines_the_spec_gives(self) -> None:
        stamped = workout.stamped(self.body, self.plan, fixtures.NOW)
        self.assertEqual(
            stamped["description"].splitlines(),
            [
                "Synced from Hevy: https://github.com/zimmertr/hevy-garmin-sync",
                f"Last updated: {fixtures.NOW:%Y-%m-%d %H:%M} PST",
                "Hevy routine: routine-1",
                f"Version: {workout.version(self.body)}",
            ],
        )
        self.assertEqual({k: v for k, v in stamped.items() if k != "description"}, self.body)

    def test_a_trainer_workout_names_its_template(self) -> None:
        plan = Workout(workout.TRAINER, "template-9", "Hevy/Trainer: Upper (C2-W2)", self.plan.exercises)
        stamped = workout.stamped(workout.build(plan, "statute_us"), plan, fixtures.NOW)
        self.assertIn("\nHevy Trainer template: template-9\n", stamped["description"])
        body = {k: v for k, v in stamped.items() if k != "description"}
        self.assertEqual(
            workout.owner(stamped["description"]), Owner(workout.TRAINER, "template-9", workout.version(body))
        )

    def test_the_version_is_six_hex_digits_of_the_workout_as_built(self) -> None:
        self.assertRegex(workout.version(self.body), r"^[0-9a-f]{6}$")
        self.assertEqual(workout.version(self.body), workout.version(workout.build(self.plan, "statute_us")))

    def test_the_version_changes_with_the_name_the_steps_and_the_unit(self) -> None:
        renamed = workout.build(routine(*self.plan.exercises, name="Hevy: Abs"), "statute_us")
        heavier = workout.build(routine(side_bend(Set(reps=12, weight_kg=20))), "statute_us")
        versions = {workout.version(b) for b in (self.body, renamed, heavier)}
        self.assertEqual(len(versions), 3)
        in_pounds = workout.build(routine(side_bend(Set(reps=12, weight_kg=20))), "statute_us")
        in_kilograms = workout.build(routine(side_bend(Set(reps=12, weight_kg=20))), "metric")
        self.assertNotEqual(workout.version(in_pounds), workout.version(in_kilograms))

    def test_the_owner_reads_back_from_the_description(self) -> None:
        stamped = workout.stamped(self.body, self.plan, fixtures.NOW)
        self.assertEqual(
            workout.owner(stamped["description"]), Owner(workout.ROUTINE, "routine-1", workout.version(self.body))
        )

    def test_the_owner_survives_garmin_flattening_the_line_breaks(self) -> None:
        stamped = workout.stamped(self.body, self.plan, fixtures.NOW)
        for flattened in (stamped["description"].replace("\n", " "), stamped["description"].replace("\n", "\r\n")):
            with self.subTest(flattened=flattened):
                self.assertEqual(
                    workout.owner(flattened), Owner(workout.ROUTINE, "routine-1", workout.version(self.body))
                )

    def test_a_workout_is_not_the_apps_without_the_first_line_and_an_id(self) -> None:
        for description in (
            None,
            "",
            "Leg day",
            "Hevy routine: routine-1",
            workout.FIRST_LINE,
            f"{workout.FIRST_LINE}\nLast updated: never",
            f"A note first\n{workout.FIRST_LINE}\nHevy routine: routine-1",
        ):
            with self.subTest(description=description):
                self.assertIsNone(workout.owner(description))

    def test_a_missing_version_reads_as_none_so_the_workout_is_rewritten(self) -> None:
        owned = workout.owner(f"{workout.FIRST_LINE}\nHevy routine: routine-1")
        self.assertEqual(owned, Owner(workout.ROUTINE, "routine-1", None))


if __name__ == "__main__":
    unittest.main()
