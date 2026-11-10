"""Hevy Trainer's arithmetic gives the answers the Hevy app gave (spec F-41 to F-47, D-10)."""

import unittest
from datetime import datetime, timedelta
from typing import Any

from hevy_garmin_sync import trainer_rules as tr
from tests import fixtures

LBS = (5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 30, 35, 40, 45, 50)
DUMBBELLS = tr.Equipment("dumbbell", "lbs", dumbbells=LBS)
MACHINE = tr.Equipment("machine", "lbs")


def kg(lbs: float) -> float:
    return lbs / tr.LBS_PER_KG


def sets(*reps: int, weight: float = 35, kind: str = "normal") -> list[dict[str, Any]]:
    return [{"type": kind, "reps": r, "weight_kg": kg(weight)} for r in reps]


class UnitsTest(unittest.TestCase):
    def test_a_weight_reads_in_its_unit_to_two_decimals_halves_up(self) -> None:
        self.assertEqual(tr.in_unit(kg(50), "lbs"), 50)
        self.assertEqual(tr.in_unit(22.6796, "kg"), 22.68)
        self.assertEqual(tr.in_unit(1.005 + 1e-9, "kg"), 1.01)
        self.assertAlmostEqual(tr.to_kg(2.20462, "lbs"), 1)
        self.assertEqual(tr.to_kg(20, "kg"), 20)


class WeekTest(unittest.TestCase):
    """The program in these cases was made on a Monday evening; `fixtures` holds its dates."""

    def week(self, now: datetime, first: str = "monday") -> int:
        return tr.program_week(fixtures.PROGRAM_START, now, first, fixtures.ZONE)

    def test_weeks_are_counted_from_the_week_the_program_was_made_in(self) -> None:
        start = fixtures.PROGRAM_START.astimezone(fixtures.ZONE)
        monday = datetime.combine(start.date(), datetime.min.time(), tzinfo=fixtures.ZONE)
        self.assertEqual(self.week(start), 1)
        self.assertEqual(self.week(monday + timedelta(days=6, hours=23, minutes=59)), 1)
        self.assertEqual(self.week(monday + timedelta(days=7)), 2)

    def test_the_week_the_app_showed_as_cycle_2_week_2(self) -> None:
        week = self.week(fixtures.PROGRAM_WEEK_8, first="sunday")
        self.assertEqual(week, 8)
        self.assertEqual((tr.cycle(week, False), tr.week_of_cycle(week, False)), (2, 2))
        self.assertEqual(self.week(fixtures.PROGRAM_WEEK_8), 8)

    def test_the_week_turns_at_midnight_on_the_users_first_weekday(self) -> None:
        sunday = fixtures.PROGRAM_WEEK_8 + timedelta(days=2)
        self.assertEqual(sunday.strftime("%A"), "Sunday")
        self.assertEqual(self.week(sunday, first="sunday"), 9)
        self.assertEqual(self.week(sunday, first="monday"), 8)
        self.assertEqual(self.week(sunday, first="nonsense"), 8)
        self.assertEqual(tr.week_start(sunday, "sunday", fixtures.ZONE), sunday.date())
        self.assertEqual(tr.week_start(sunday, "monday", fixtures.ZONE), sunday.date() - timedelta(days=6))

    def test_cycles_are_six_weeks_or_seven_with_a_deload(self) -> None:
        self.assertEqual((tr.cycle(6, False), tr.week_of_cycle(6, False)), (1, 6))
        self.assertEqual((tr.cycle(0, False), tr.week_of_cycle(0, False)), (1, 1))
        self.assertEqual((tr.cycle(8, True), tr.week_of_cycle(8, True)), (2, 1))
        self.assertEqual((tr.weeks_in_cycle(False), tr.weeks_in_cycle(True)), (6, 7))
        self.assertTrue(tr.is_deload_week(7, True))
        self.assertFalse(tr.is_deload_week(6, True))
        self.assertFalse(tr.is_deload_week(7, False))


class EquipmentTest(unittest.TestCase):
    def test_the_users_own_weights_are_used_and_defaults_fill_in(self) -> None:
        owned = tr.equipment("dumbbell", "lbs", {"dumbbellsLbs": [5, 10]})
        self.assertEqual(owned.dumbbells if owned else None, (5, 10))
        default = tr.equipment("dumbbell", "kg", {})
        self.assertEqual(default.dumbbells if default else None, tuple(tr.DEFAULT_WEIGHTS["dumbbellsKg"]))
        bar = tr.equipment("barbell", "lbs", {"barsLbs": [45], "platesLbs": [10, 5]})
        self.assertEqual((bar.bars, bar.plates) if bar else None, ((45,), (10, 5)))
        self.assertEqual(tr.equipment("machine", "kg", {}), tr.Equipment("machine", "kg"))

    def test_other_equipment_gets_no_suggestion(self) -> None:
        for kind in ("kettlebell", "none", "other", "plate", "resistance_band", "suspension", None):
            with self.subTest(kind=kind):
                self.assertIsNone(tr.equipment(kind, "lbs", {}))


class LoadableTest(unittest.TestCase):
    """Dumbbells of 20, 25, 30 and 35 lb: pairs of 40, 50, 60 and 70."""

    PAIRS = tr.Equipment("dumbbell", "lbs", dumbbells=(35, 20, 30, 25))

    def pick(self, target: float, direction: str | None = None, current: float | None = None) -> float | None:
        return tr.loadable(kg(target), self.PAIRS, direction, current)

    def test_with_no_direction_it_is_the_nearest_and_the_lighter_on_a_tie(self) -> None:
        self.assertEqual(self.pick(52), 50)
        self.assertEqual(self.pick(55, None, 50), 50)
        self.assertEqual(self.pick(66, "increase", None), 70)

    def test_an_increase_never_lands_at_or_below_the_current_weight(self) -> None:
        self.assertEqual(self.pick(60, "increase", 50), 60)  # the target itself
        self.assertEqual(self.pick(65, "increase", 40), 60)  # the heaviest short of the target
        self.assertEqual(self.pick(52.5, "increase", 50), 60)  # the next one up
        self.assertIsNone(self.pick(73.5, "increase", 70))  # nothing heavier is owned

    def test_a_decrease_never_lands_at_or_above_it(self) -> None:
        self.assertEqual(self.pick(50, "decrease", 60), 50)
        self.assertEqual(self.pick(45, "decrease", 70), 50)
        self.assertEqual(self.pick(57, "decrease", 60), 50)
        self.assertIsNone(self.pick(38, "decrease", 40))

    def test_no_change_keeps_the_current_weight(self) -> None:
        self.assertEqual(self.pick(52, "none", 50), 50)

    def test_no_dumbbells_means_no_weight(self) -> None:
        self.assertIsNone(tr.loadable(kg(50), tr.Equipment("dumbbell", "lbs")))
        self.assertIsNone(tr.loadable(kg(50), tr.Equipment("dumbbell", "lbs"), "none", 50))

    def test_a_machine_moves_in_steps_of_5_lb_or_2_5_kg(self) -> None:
        self.assertEqual(tr.loadable(kg(101), MACHINE, "increase"), 105)
        self.assertEqual(tr.loadable(kg(104), MACHINE, "decrease"), 100)
        self.assertEqual(tr.loadable(kg(102.5), MACHINE), 105)
        self.assertEqual(tr.loadable(41, tr.Equipment("machine", "kg")), 40)
        self.assertEqual(tr.loadable(41.25, tr.Equipment("machine", "kg")), 42.5)

    def test_a_barbell_is_a_bar_plus_two_equal_sides(self) -> None:
        bar = tr.Equipment("barbell", "lbs", bars=(45,), plates=(10, 5, 0))
        self.assertEqual(tr.loadable(kg(68), bar, "increase", 65), 75)
        self.assertEqual(tr.loadable(kg(56), bar), 55)
        self.assertEqual(tr.loadable(kg(40), bar), 45)

    def test_a_barbell_with_no_usable_bar_gets_the_default_bar(self) -> None:
        no_bar = tr.Equipment("barbell", "kg", bars=(0,), plates=(5,))
        self.assertEqual(tr.loadable(22, no_bar), 20)
        self.assertEqual(tr.loadable(27, no_bar), 30)


class WeightTest(unittest.TestCase):
    RANGE = (10, 12)

    def next(self, *logs: list[dict[str, Any]], warmups: int = 0, deload: bool = False) -> tr.Prescription | None:
        return tr.next_weight(logs, 3, self.RANGE, warmups, DUMBBELLS, deload)

    def result(self, *logs: list[dict[str, Any]], **kwargs: Any) -> tuple[str, float | None, tuple[float, ...]]:
        found = self.next(*logs, **kwargs)
        assert found is not None
        return found.direction, found.weight, found.warmups

    def test_every_set_at_the_top_of_the_range_adds_five_percent(self) -> None:
        # Side Bend, checked against the app: 35 lb for 15, 12, 12 became 40 lb.
        self.assertEqual(self.result(sets(9, 9, 9), sets(15, 12, 12)), ("increase", 40, ()))

    def test_every_set_short_of_the_bottom_takes_five_percent_off(self) -> None:
        self.assertEqual(self.result(sets(9, 8, 9)), ("decrease", 30, ()))

    def test_anything_in_between_keeps_the_weight(self) -> None:
        self.assertEqual(self.result(sets(12, 12, 11)), ("none", 35, ()))
        self.assertEqual(self.result(sets(12, 9, 9)), ("none", 35, ()))

    def test_fewer_sets_than_planned_keeps_the_weight(self) -> None:
        self.assertEqual(self.result(sets(12, 12)), ("none", 35, ()))

    def test_only_the_latest_session_counts_and_warm_ups_are_ignored(self) -> None:
        latest = sets(5, kind="warmup", weight=10) + sets(12, 12, 12)
        self.assertEqual(self.result(sets(1, 1, 1), latest), ("increase", 40, ()))

    def test_the_lightest_working_set_is_the_base(self) -> None:
        log = sets(12, weight=50) + sets(12, 12, weight=30)
        self.assertEqual(self.result(log), ("increase", 35, ()))

    def test_a_set_logged_without_reps_or_weight_counts_as_zero(self) -> None:
        log = [{"type": "normal", "reps": None, "weight_kg": kg(35)}] * 3
        self.assertEqual(self.result(log), ("decrease", 30, ()))
        # No weight is a base of zero, so "5% more" is the lightest pair there is.
        self.assertEqual(self.result([{"type": "normal", "reps": 12, "weight_kg": None}] * 3), ("increase", 10, ()))

    def test_no_history_or_no_working_set_gives_nothing(self) -> None:
        self.assertIsNone(self.next())
        self.assertIsNone(self.next(sets(1, kind="warmup")))

    def test_a_weight_past_what_the_user_owns_gives_nothing(self) -> None:
        self.assertIsNone(self.next(sets(12, 12, 12, weight=100)))

    def test_a_deload_week_is_sixty_percent_of_the_suggestion(self) -> None:
        self.assertEqual(self.result(sets(12, 12, 12, weight=50), warmups=1, deload=True), ("deload", 35, (20,)))

    def test_a_prescription_gives_kilograms_for_the_workout(self) -> None:
        found = self.next(sets(15, 12, 12), warmups=1)
        assert found is not None
        self.assertAlmostEqual(found.weight_kg or 0, kg(40))
        self.assertEqual(found.unit, "lbs")
        self.assertEqual(len(found.warmups_kg), 1)
        self.assertIsNone(tr.Prescription("none").weight_kg)
        self.assertEqual(tr.Prescription("none", 20, "kg", (10,)).warmups_kg, (10,))


class WarmupTest(unittest.TestCase):
    def test_one_warm_up_is_sixty_percent_and_two_are_forty_and_sixty(self) -> None:
        # Goblet Squat, checked against the app: 80 lb working sets gave warm-ups of 30 and 50 lb.
        self.assertEqual(tr.warmups(80, 2, DUMBBELLS), (30, 50))
        self.assertEqual(tr.warmups(80, 1, DUMBBELLS), (50,))
        self.assertEqual(tr.warmups(40, 1, tr.Equipment("machine", "kg")), (25,))

    def test_no_weight_no_warm_ups_or_no_dumbbells_gives_none(self) -> None:
        self.assertEqual(tr.warmups(None, 2, DUMBBELLS), ())
        self.assertEqual(tr.warmups(80, 0, DUMBBELLS), ())
        self.assertEqual(tr.warmups(80, 2, tr.Equipment("dumbbell", "lbs")), ())

    def test_the_program_asks_for_none_one_or_two(self) -> None:
        cases = ((None, 0), (float("inf"), 0), (-1, 0), (0, 0), (True, 0), ("2", 0), (1, 1), (1.5, 1), (2, 2), (5, 2))
        for given, want in cases:
            with self.subTest(given=given):
                self.assertEqual(tr.warmup_count(given), want)


class StartingWeightTest(unittest.TestCase):
    def test_a_one_rep_max_is_the_weight_over_the_factor_for_the_reps(self) -> None:
        self.assertEqual(tr.one_rep_max_kg(100, 1), 100)
        self.assertAlmostEqual(tr.one_rep_max_kg(75, 10), 100)
        self.assertAlmostEqual(tr.one_rep_max_kg(50, 30), 100)
        self.assertAlmostEqual(tr.one_rep_max_kg(50, 45), 100)
        self.assertEqual(tr.one_rep_max_kg(100, 0), 0)
        self.assertEqual(len(tr.ONE_REP_MAX_FACTORS), 30)

    def test_a_new_exercise_starts_at_a_share_of_the_one_rep_max_for_its_rep_range(self) -> None:
        cases = (((4, 6), 80), ((5, 6), 80), ((10, 12), 65), ((8, 12), 65), ((8, 10), 65), ((12, 15), 65))
        for rep_range, weight in cases:
            with self.subTest(rep_range=rep_range):
                found = tr.starting_weight(kg(100), rep_range, 0, MACHINE)
                self.assertEqual((found.direction, found.weight) if found else None, ("new", weight))

    def test_the_shares_are_80_64_67_and_63_percent(self) -> None:
        precise = tr.Equipment("barbell", "kg", bars=(0.01,), plates=(0.005,))
        cases = (((4, 6), 0.8), ((10, 12), 0.64), ((8, 12), 0.67), ((12, 15), 0.63))
        for rep_range, share in cases:
            with self.subTest(rep_range=rep_range):
                found = tr.starting_weight(1, rep_range, 0, precise)
                self.assertEqual(found.weight if found else None, share)

    def test_it_comes_with_its_warm_ups(self) -> None:
        found = tr.starting_weight(kg(100), (8, 12), 2, DUMBBELLS)
        self.assertEqual((found.weight, found.warmups) if found else None, (70, (30, 40)))

    def test_no_one_rep_max_or_a_rep_range_outside_the_table_gives_nothing(self) -> None:
        self.assertIsNone(tr.starting_weight(None, (8, 12), 0, MACHINE))
        self.assertIsNone(tr.starting_weight(0, (8, 12), 0, MACHINE))
        for rep_range in ((15, 20), (6, 8), (3, 5), (20, 25)):
            with self.subTest(rep_range=rep_range):
                self.assertIsNone(tr.starting_weight(kg(100), rep_range, 0, MACHINE))
        self.assertIsNone(tr.starting_weight(kg(100), (8, 12), 0, tr.Equipment("dumbbell", "lbs")))


class RepsTest(unittest.TestCase):
    BASE = (10, 12)

    def next(self, *logs: list[dict[str, Any]], base: tr.RepRange = BASE, deload: bool = False) -> tr.Prescription:
        return tr.next_rep_range(logs, 3, base, deload)

    def test_each_session_moves_the_range_a_rung(self) -> None:
        # Lying Leg Raise, checked against the app: it reached 15-20 reps.
        logs = [sets(12, 13, 12), sets(15, 15, 15), sets(16, 15, 15), sets(1, kind="warmup")]
        found = self.next(*logs[:2])
        self.assertEqual((found.direction, found.rep_range), ("increase", (15, 20)))
        found = self.next(*logs)
        self.assertEqual((found.direction, found.rep_range), ("none", (15, 20)))
        self.assertIsNone(found.weight)

    def test_falling_short_moves_it_down_and_too_few_sets_leave_it(self) -> None:
        self.assertEqual(self.next(sets(5, 5, 5)).rep_range, (8, 12))
        self.assertEqual(self.next(sets(5, 5)).direction, "none")

    def test_the_ladder_has_two_ends(self) -> None:
        top, bottom = (25, 30), (4, 6)
        self.assertEqual(self.next(sets(30, 30, 30), base=top).rep_range, top)
        self.assertEqual(self.next(sets(1, 1, 1), base=bottom).rep_range, bottom)

    def test_an_exercise_never_logged_starts_at_the_programs_range(self) -> None:
        found = self.next()
        self.assertEqual((found.direction, found.rep_range), ("new", self.BASE))

    def test_a_deload_week_is_one_rung_down(self) -> None:
        self.assertEqual(self.next(deload=True).rep_range, (8, 12))
        self.assertEqual(self.next(base=(4, 6), deload=True).rep_range, (4, 6))
        self.assertEqual(self.next(deload=True).direction, "deload")


if __name__ == "__main__":
    unittest.main()
