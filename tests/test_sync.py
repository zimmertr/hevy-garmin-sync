"""Garmin is made to match the plan: workouts, Send to Device and today's calendar (spec F-3, sections 3 and 5)."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from hevy_garmin_sync import errors, garmin, workout
from hevy_garmin_sync.store import Store
from hevy_garmin_sync.sync import Counts, Plans, Sync
from hevy_garmin_sync.workout import Exercise, Set, Workout
from tests import fixtures

WRITES = {
    "upload_workout",
    "update_workout",
    "delete_workout",
    "push_workout_to_device",
    "schedule_workout",
    "unschedule_workout",
}


def routine(source_id: str, name: str, reps: int = 8, kind: str = workout.ROUTINE) -> Workout:
    bench = Exercise("Bench Press (Barbell)", "BENCH_PRESS", "BARBELL_BENCH_PRESS", (Set(reps=reps, weight_kg=60),), 90)
    return Workout(kind, source_id, name, (bench,))


def plans(*workouts: Workout, **fields: Any) -> list[Plans]:
    return [Plans(workout.ROUTINE, workouts, **fields)]


class SyncCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.api = fixtures.FakeGarminApi()
        self.pacing = clock = fixtures.FakeClock()
        self.garmin = garmin.Garmin(self.api, Store(Path(folder.name)), sleep=clock.sleep, clock=clock)  # type: ignore[arg-type]
        self.time = fixtures.NOW
        self.sync = self.new_sync()
        self.push = routine("r-push", "Hevy: Push")
        self.pull = routine("r-pull", "Hevy: Pull")

    def new_sync(self, scheduled: bool = True) -> Sync:
        """A sync with nothing in memory, as after a restart."""
        return Sync(self.garmin, scheduled, lambda: self.time)

    def run_full(self, *workouts: Workout, **fields: Any) -> Counts:
        return self.sync.run(plans(*workouts, **fields), full=True)

    def run_poll(self, *workouts: Workout, **fields: Any) -> Counts:
        return self.sync.run(plans(*workouts, **fields), full=False)

    def writes(self) -> list[str]:
        return [call for call in self.api.calls if call in WRITES]

    def names(self) -> list[str]:
        return sorted(w["workoutName"] for w in self.api.workouts.values())

    def id_of(self, name: str) -> int:
        (found,) = [wid for wid, w in self.api.workouts.items() if w["workoutName"] == name]
        return found

    def days(self) -> dict[str, list[str]]:
        """Workout name -> the days it is on the calendar."""
        found: dict[str, list[str]] = {}
        for entry in self.api.entries.values():
            name = self.api.workouts[entry["workout"]["workoutId"]]["workoutName"]
            found.setdefault(name, []).append(entry["calendarDate"])
        return found


class WorkoutsTest(SyncCase):
    def test_the_first_run_creates_sends_and_schedules_every_workout(self) -> None:
        counts = self.run_full(self.push, self.pull)
        self.assertEqual(self.names(), ["Hevy: Pull", "Hevy: Push"])
        self.assertEqual(sorted(self.api.pushed), sorted(self.api.workouts))
        self.assertEqual(
            self.days(), {"Hevy: Push": [fixtures.TODAY.isoformat()], "Hevy: Pull": [fixtures.TODAY.isoformat()]}
        )
        self.assertEqual(
            (counts.created, counts.scheduled, counts.updated, counts.deleted, counts.failed), (2, 2, 0, 0, 0)
        )

    def test_a_created_workout_says_whose_it_is(self) -> None:
        self.run_full(self.push)
        stored = self.api.workouts[self.id_of("Hevy: Push")]
        owner = workout.owner(stored["description"])
        self.assertEqual((owner.kind, owner.source_id) if owner else None, (workout.ROUTINE, "r-push"))
        self.assertIn(f"Last updated: {fixtures.NOW:%Y-%m-%d %H:%M} PST", stored["description"])

    def test_a_run_with_nothing_changed_makes_no_garmin_call(self) -> None:
        self.run_full(self.push, self.pull)
        self.api.calls.clear()
        counts = self.run_poll(self.push, self.pull)
        self.assertEqual(self.api.calls, [])
        self.assertFalse(counts.any())

    def test_a_changed_routine_updates_its_workout_in_place_and_sends_it_again(self) -> None:
        self.run_full(self.push)
        workout_id = self.id_of("Hevy: Push")
        self.api.calls.clear()
        counts = self.run_poll(routine("r-push", "Hevy: Push v2", reps=10))
        self.assertEqual(self.api.calls, ["update_workout", "push_workout_to_device"])
        self.assertEqual(self.id_of("Hevy: Push v2"), workout_id)
        self.assertEqual((counts.updated, counts.created, counts.scheduled), (1, 0, 0))

    def test_a_restart_recognizes_its_workouts_and_creates_no_duplicates(self) -> None:
        self.run_full(self.push, self.pull)
        self.api.calls.clear()
        self.sync = self.new_sync()
        counts = self.run_full(self.push, self.pull)
        self.assertEqual(self.writes(), [])
        self.assertFalse(counts.any())
        self.assertEqual(len(self.api.workouts), 2)

    def test_a_restart_updates_what_changed_while_the_app_was_down(self) -> None:
        self.run_full(self.push)
        self.sync = self.new_sync()
        counts = self.run_full(routine("r-push", "Hevy: Push", reps=12))
        self.assertEqual((counts.updated, counts.created), (1, 0))

    def test_a_hand_edit_in_garmin_stays_until_the_routine_changes(self) -> None:
        self.run_full(self.push)
        self.api.workouts[self.id_of("Hevy: Push")]["workoutSegments"] = "edited by hand"
        self.sync = self.new_sync()
        self.run_full(self.push)
        self.assertEqual(self.api.workouts[self.id_of("Hevy: Push")]["workoutSegments"], "edited by hand")

    def test_a_workout_with_no_version_line_is_rewritten(self) -> None:
        self.run_full(self.push)
        stored = self.api.workouts[self.id_of("Hevy: Push")]
        stored["description"] = stored["description"].split("\nVersion")[0]
        self.sync = self.new_sync()
        self.assertEqual(self.run_full(self.push).updated, 1)

    def test_workouts_the_app_did_not_create_are_never_touched(self) -> None:
        self.api.workouts[1] = {"workoutId": 1, "workoutName": "Tempo Run", "description": "from a running app"}
        self.api.workouts[2] = {"workoutId": 2, "workoutName": "Mine", "description": None}
        self.run_full(self.push)
        self.run_poll()
        self.run_poll()
        self.assertEqual(self.names(), ["Mine", "Tempo Run"])

    def test_the_unit_follows_the_garmin_profile_read_at_each_full_run(self) -> None:
        self.api.measurement_system = "metric"
        self.run_full(self.push)
        steps = self.api.workouts[self.id_of("Hevy: Push")]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual((steps[0]["weightValue"], steps[0]["weightUnit"]["unitKey"]), (60.0, "kilogram"))
        self.api.measurement_system = "statute_us"
        self.assertEqual(self.run_full(self.push).updated, 1)

    def test_two_workouts_claiming_one_routine_are_cut_to_one(self) -> None:
        self.run_full(self.push)
        copy = dict(self.api.workouts[self.id_of("Hevy: Push")]) | {"workoutId": 5}
        self.api.workouts[5] = copy
        self.sync = self.new_sync()
        with self.assertLogs("hevy_garmin_sync.sync", "WARNING"):
            counts = self.run_full(self.push)
        self.assertEqual((len(self.api.workouts), counts.deleted), (1, 1))

    def test_a_garmin_outage_mid_run_raises_and_the_next_full_run_finishes_the_job(self) -> None:
        self.api.fail("push_workout_to_device", fixtures.garmin_error(503))
        with self.assertRaises(errors.Unavailable):
            self.run_full(self.push, self.pull)
        self.assertEqual(self.names(), ["Hevy: Push"])
        self.sync = self.new_sync()
        self.run_full(self.push, self.pull)
        self.assertEqual(self.names(), ["Hevy: Pull", "Hevy: Push"])


class SendTest(SyncCase):
    def test_a_send_that_failed_is_made_again_by_the_next_run(self) -> None:
        self.api.fail("push_workout_to_device", fixtures.garmin_error(503))
        with self.assertRaises(errors.Unavailable):
            self.run_full(self.push)
        self.assertEqual(self.api.pushed, [])
        self.api.calls.clear()
        self.run_poll(self.push)
        self.assertEqual(self.api.pushed, [self.id_of("Hevy: Push")])
        self.assertEqual(self.writes(), ["push_workout_to_device"])

    def test_an_account_with_no_watch_is_warned_about_once_and_still_syncs(self) -> None:
        self.api.fail("push_workout_to_device", KeyError("userDeviceId"), KeyError("userDeviceId"))
        with self.assertLogs("hevy_garmin_sync.sync", "WARNING") as logs:
            counts = self.run_full(self.push, self.pull)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("still on the calendar", logs.output[0])
        self.assertEqual((counts.created, counts.scheduled), (2, 2))
        self.api.calls.clear()
        self.run_poll(self.push, self.pull)
        self.assertEqual(self.api.calls, [])


class DeleteTest(SyncCase):
    def test_a_routine_is_deleted_only_when_two_runs_in_a_row_miss_it(self) -> None:
        self.run_full(self.push, self.pull)
        first = self.run_poll(self.push)
        self.assertEqual((first.deleted, self.names()), (0, ["Hevy: Pull", "Hevy: Push"]))
        second = self.run_poll(self.push)
        self.assertEqual((second.deleted, second.unscheduled, self.names()), (1, 1, ["Hevy: Push"]))
        self.assertEqual(self.days(), {"Hevy: Push": [fixtures.TODAY.isoformat()]})

    def test_a_routine_missing_from_one_read_and_back_in_the_next_is_kept(self) -> None:
        self.run_full(self.push, self.pull)
        self.run_poll(self.push)
        self.run_poll(self.push, self.pull)
        self.run_poll(self.push)
        self.assertEqual(self.names(), ["Hevy: Pull", "Hevy: Push"])

    def test_the_calendar_entry_goes_before_the_workout(self) -> None:
        self.run_full(self.push)
        self.run_poll()
        self.api.calls.clear()
        self.run_poll()
        self.assertEqual(self.api.calls, ["unschedule_workout", "delete_workout"])

    def test_a_held_kind_is_never_deleted(self) -> None:
        self.run_full(self.push, self.pull)
        for _ in range(3):
            self.run_poll(self.push, hold=True)
        self.assertEqual(self.names(), ["Hevy: Pull", "Hevy: Push"])

    def test_a_kind_nobody_plans_for_any_more_is_deleted(self) -> None:
        trainer = routine("t-1", "Hevy/Trainer: Upper (C1-W1)", kind=workout.TRAINER)
        both = [Plans(workout.ROUTINE, [self.push]), Plans(workout.TRAINER, [trainer])]
        self.sync.run(both, full=True)
        without = [Plans(workout.ROUTINE, [self.push]), Plans(workout.TRAINER, [])]
        self.sync.run(without, full=False)
        self.sync.run(without, full=False)
        self.assertEqual(self.names(), ["Hevy: Push"])


class RefusedTest(SyncCase):
    def refuse(self, method: str = "upload_workout") -> None:
        self.api.fail(method, fixtures.garmin_error(400, "Too many steps"))

    def test_a_refused_workout_is_logged_and_skipped_and_the_rest_sync(self) -> None:
        self.refuse()
        with self.assertLogs("hevy_garmin_sync.sync", "ERROR") as logs:
            counts = self.run_full(self.push, self.pull)
        self.assertIn("Garmin refused 'Hevy: Push' (2 steps): API Error 400 - Too many steps", logs.output[0])
        self.assertEqual((counts.failed, counts.created, self.names()), (1, 1, ["Hevy: Pull"]))

    def test_it_is_not_tried_again_on_the_next_poll(self) -> None:
        self.refuse()
        with self.assertLogs("hevy_garmin_sync.sync", "ERROR"):
            self.run_full(self.push)
        self.api.calls.clear()
        self.assertFalse(self.run_poll(self.push).any())
        self.assertEqual(self.api.calls, [])

    def test_it_is_tried_again_when_the_routine_changes(self) -> None:
        self.refuse()
        with self.assertLogs("hevy_garmin_sync.sync", "ERROR"):
            self.run_full(self.push)
        self.assertEqual(self.run_poll(routine("r-push", "Hevy: Push", reps=5)).created, 1)

    def test_it_is_tried_again_at_the_next_full_run(self) -> None:
        self.refuse()
        with self.assertLogs("hevy_garmin_sync.sync", "ERROR"):
            self.run_full(self.push)
        self.assertEqual(self.run_full(self.push).created, 1)

    def test_a_refused_update_keeps_the_old_workout(self) -> None:
        self.run_full(self.push)
        self.refuse("update_workout")
        with self.assertLogs("hevy_garmin_sync.sync", "ERROR"):
            counts = self.run_poll(routine("r-push", "Hevy: Push v2"))
        self.assertEqual((counts.failed, counts.updated, self.names()), (1, 0, ["Hevy: Push"]))
        self.run_poll(routine("r-push", "Hevy: Push v2"))
        self.assertEqual(self.names(), ["Hevy: Push"])

    def test_a_routine_with_no_exercises_gets_no_workout_and_says_so_once(self) -> None:
        empty = Workout(workout.ROUTINE, "r-empty", "Hevy: Empty", ())
        no_sets = Workout(workout.ROUTINE, "r-bare", "Hevy: Bare", (Exercise("Bench", "BENCH_PRESS", "", ()),))
        with self.assertLogs("hevy_garmin_sync.sync", "INFO") as logs:
            self.run_full(self.push, empty, no_sets)
        self.assertEqual(len(logs.output), 2)
        self.assertIn("'Hevy: Empty' has no exercises", logs.output[0])
        self.assertEqual(self.names(), ["Hevy: Push"])
        with self.assertNoLogs("hevy_garmin_sync.sync", "INFO"):
            self.run_poll(self.push, empty, no_sets)

    def test_a_routine_emptied_later_loses_its_workout(self) -> None:
        self.run_full(self.push)
        emptied = Workout(workout.ROUTINE, "r-push", "Hevy: Push", ())
        self.run_poll(emptied)
        self.run_poll(emptied)
        self.assertEqual(self.names(), [])


class CalendarTest(SyncCase):
    def on(self, name: str, day: datetime) -> None:
        self.api.schedule_workout(self.id_of(name), day.date().isoformat())

    def test_at_midnight_past_entries_go_and_each_workout_is_on_the_new_day(self) -> None:
        self.run_full(self.push, self.pull)
        self.time += timedelta(days=1)
        counts = self.run_full(self.push, self.pull)
        tomorrow = (fixtures.TODAY + timedelta(days=1)).isoformat()
        self.assertEqual(self.days(), {"Hevy: Push": [tomorrow], "Hevy: Pull": [tomorrow]})
        self.assertEqual((counts.unscheduled, counts.scheduled), (2, 2))

    def test_a_full_run_on_the_same_day_changes_nothing(self) -> None:
        self.run_full(self.push)
        self.api.calls.clear()
        self.assertFalse(self.run_full(self.push).any())
        self.assertEqual(self.writes(), [])

    def test_entries_up_to_31_days_back_are_removed_and_older_or_later_ones_are_left(self) -> None:
        self.run_full(self.push)
        for days in (-40, -31, -3, 2):
            self.on("Hevy: Push", self.time + timedelta(days=days))
        self.run_full(self.push)
        kept = sorted(self.days()["Hevy: Push"])
        expected = sorted((fixtures.TODAY + timedelta(days=d)).isoformat() for d in (-40, 0, 2))
        self.assertEqual(kept, expected)

    def test_a_second_entry_on_today_is_removed(self) -> None:
        self.run_full(self.push)
        self.on("Hevy: Push", self.time)
        self.assertEqual(self.run_full(self.push).unscheduled, 1)
        self.assertEqual(self.days(), {"Hevy: Push": [fixtures.TODAY.isoformat()]})

    def test_entries_of_other_workouts_are_never_touched(self) -> None:
        self.api.workouts[1] = {"workoutId": 1, "workoutName": "Tempo Run", "description": "from a running app"}
        self.api.schedule_workout(1, (fixtures.TODAY - timedelta(days=2)).isoformat())
        self.run_full(self.push)
        self.assertEqual(self.days()["Tempo Run"], [(fixtures.TODAY - timedelta(days=2)).isoformat()])

    def test_an_entry_with_no_id_is_skipped(self) -> None:
        self.run_full(self.push)
        self.api.entries[9] = {
            "calendarDate": fixtures.TODAY.isoformat(),
            "workout": {"workoutId": self.id_of("Hevy: Push")},
        }
        self.api.entries[10] = {"calendarDate": fixtures.TODAY.isoformat(), "workoutScheduleId": 10}
        self.api.calls.clear()
        self.run_full(self.push)
        self.assertEqual(self.writes(), [])

    def test_with_the_calendar_off_nothing_is_scheduled_and_old_entries_are_removed(self) -> None:
        self.run_full(self.push)
        self.sync = self.new_sync(scheduled=False)
        counts = self.run_full(self.push, self.pull)
        self.assertEqual(self.days(), {})
        self.assertEqual((counts.unscheduled, counts.scheduled, counts.created), (1, 0, 1))
        self.assertEqual(len(self.api.pushed), 2)

    def test_a_full_run_leaves_a_workout_held_off_the_calendar_off_it(self) -> None:
        self.run_full(self.push, self.pull)
        self.sync = self.new_sync()
        counts = self.run_full(self.push, self.pull, off_calendar=frozenset({"r-pull"}))
        self.assertEqual((counts.unscheduled, counts.scheduled), (1, 0))
        self.assertEqual(self.days(), {"Hevy: Push": [fixtures.TODAY.isoformat()]})
        self.assertEqual(self.names(), ["Hevy: Pull", "Hevy: Push"])

    def test_a_workout_created_while_held_off_the_calendar_gets_no_entry(self) -> None:
        counts = self.run_full(self.push, off_calendar=frozenset({"r-push"}))
        self.assertEqual((counts.created, counts.scheduled, self.days()), (1, 0, {}))

    def test_a_workout_created_between_full_runs_is_put_on_today(self) -> None:
        self.run_full(self.push)
        self.api.calls.clear()
        self.run_poll(self.push, self.pull)
        self.assertEqual(self.writes(), ["upload_workout", "schedule_workout", "push_workout_to_device"])
        self.assertEqual(self.days()["Hevy: Pull"], [fixtures.TODAY.isoformat()])

    def test_a_schedule_reply_without_an_id_still_counts(self) -> None:
        self.run_full(self.push)
        self.api.bare_schedule_reply = True
        self.assertEqual(self.run_poll(self.push, self.pull).scheduled, 1)
        # With no entry id to remove, the workout is deleted and Garmin drops its entry with it.
        self.run_poll(self.push)
        self.api.calls.clear()
        self.run_poll(self.push)
        self.assertEqual(self.api.calls, ["delete_workout"])


class MoveTest(SyncCase):
    """Between full runs, a workout moves on or off today in the poll that sees it change (F-31, #25)."""

    TODAY = fixtures.TODAY.isoformat()
    PUSH, PULL = frozenset({"r-push"}), frozenset({"r-pull"})

    def test_a_workout_that_leaves_the_calendar_loses_its_entry_on_that_poll(self) -> None:
        self.run_full(self.push, self.pull)
        self.api.calls.clear()
        counts = self.run_poll(self.push, self.pull, off_calendar=self.PULL)
        self.assertEqual(self.api.calls, ["unschedule_workout"])
        self.assertEqual((counts.unscheduled, counts.scheduled), (1, 0))
        self.assertEqual(self.days(), {"Hevy: Push": [self.TODAY]})
        self.assertEqual(self.names(), ["Hevy: Pull", "Hevy: Push"])

    def test_when_the_next_workout_changes_the_old_entry_goes_then_the_new_one_comes_a_second_apart(self) -> None:
        self.api.workouts[1] = {"workoutId": 1, "workoutName": "Tempo Run", "description": "from a running app"}
        self.api.schedule_workout(1, self.TODAY)
        self.run_full(self.push, self.pull, off_calendar=self.PULL)
        self.api.calls.clear()
        self.pacing.sleeps.clear()
        counts = self.run_poll(self.push, self.pull, off_calendar=self.PUSH)
        self.assertEqual(self.api.calls, ["unschedule_workout", "schedule_workout"])
        self.assertEqual((counts.unscheduled, counts.scheduled), (1, 1))
        self.assertEqual(self.days(), {"Hevy: Pull": [self.TODAY], "Tempo Run": [self.TODAY]})
        self.assertEqual(self.pacing.sleeps, [1.0, 1.0])

    def test_a_poll_where_nothing_moved_makes_no_garmin_call(self) -> None:
        self.run_full(self.push, self.pull, off_calendar=self.PULL)
        self.api.calls.clear()
        self.assertFalse(self.run_poll(self.push, self.pull, off_calendar=self.PULL).any())
        self.assertEqual(self.api.calls, [])

    def test_with_the_calendar_off_nothing_moves(self) -> None:
        self.sync = self.new_sync(scheduled=False)
        self.run_full(self.push, self.pull)
        self.api.calls.clear()
        self.run_poll(self.push, self.pull, off_calendar=self.PUSH)
        self.run_poll(self.push, self.pull, off_calendar=self.PULL)
        self.assertEqual((self.api.calls, self.days()), ([], {}))

    def test_an_entry_garmin_gave_no_id_for_stays_until_the_next_full_run(self) -> None:
        self.run_full(self.push)
        self.api.bare_schedule_reply = True
        self.run_poll(self.push, self.pull)
        self.api.calls.clear()
        self.assertFalse(self.run_poll(self.push, self.pull, off_calendar=self.PULL).any())
        self.assertEqual(self.api.calls, [])
        self.run_full(self.push, self.pull, off_calendar=self.PULL)
        self.assertEqual(self.days(), {"Hevy: Push": [self.TODAY]})

    def test_a_workout_created_on_the_poll_is_scheduled_once_or_not_at_all(self) -> None:
        self.run_full(self.push)
        self.api.calls.clear()
        self.run_poll(self.push, self.pull, off_calendar=self.PULL)
        self.assertEqual(self.writes(), ["upload_workout", "push_workout_to_device"])
        self.api.calls.clear()
        self.run_poll(self.push, self.pull, off_calendar=self.PUSH)
        self.assertEqual(sorted(self.writes()), ["schedule_workout", "unschedule_workout"])
        legs = routine("r-legs", "Hevy: Legs")
        self.api.calls.clear()
        self.run_poll(self.push, self.pull, legs, off_calendar=self.PUSH)
        self.assertEqual(self.writes().count("schedule_workout"), 1)
        self.assertEqual(self.days(), {"Hevy: Pull": [self.TODAY], "Hevy: Legs": [self.TODAY]})

    def test_a_held_kind_keeps_the_entries_of_workouts_it_does_not_list(self) -> None:
        self.run_full(self.push, self.pull)
        self.api.calls.clear()
        self.run_poll(self.push, hold=True, off_calendar=self.PULL)
        self.run_poll(hold=True, off_calendar=self.PUSH | self.PULL)
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.days(), {"Hevy: Push": [self.TODAY], "Hevy: Pull": [self.TODAY]})

    def test_a_poll_after_a_restart_moves_from_what_the_full_run_found(self) -> None:
        self.run_full(self.push, self.pull)
        self.sync = self.new_sync()
        self.run_full(self.push, self.pull, off_calendar=self.PULL)
        self.api.calls.clear()
        self.run_poll(self.push, self.pull, off_calendar=self.PULL)
        self.assertEqual(self.api.calls, [])
        self.run_poll(self.push, self.pull)
        self.assertEqual(self.api.calls, ["schedule_workout"])
        self.assertEqual(self.days(), {"Hevy: Push": [self.TODAY], "Hevy: Pull": [self.TODAY]})

    def test_a_garmin_failure_mid_move_is_put_right_by_the_next_full_run(self) -> None:
        self.run_full(self.push, self.pull, off_calendar=self.PULL)
        self.api.fail("schedule_workout", fixtures.garmin_error(503))
        with self.assertRaises(errors.Unavailable):
            self.run_poll(self.push, self.pull, off_calendar=self.PUSH)
        self.assertEqual(self.days(), {})
        self.run_full(self.push, self.pull, off_calendar=self.PUSH)
        self.assertEqual(self.days(), {"Hevy: Pull": [self.TODAY]})


class CountsTest(unittest.TestCase):
    def test_the_summary_names_every_count(self) -> None:
        counts = Counts(created=1, failed=2)
        self.assertEqual(str(counts), "created 1, updated 0, deleted 0, scheduled 0, unscheduled 0, failed 2")
        self.assertTrue(counts.any())
        self.assertFalse(Counts().any())


if __name__ == "__main__":
    unittest.main()
