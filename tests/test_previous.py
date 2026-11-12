"""Last time's working sets of each exercise: read once from its history, then kept current by the events (#3)."""

import unittest
from datetime import timedelta
from typing import Any

from hevy_garmin_sync import hevy
from hevy_garmin_sync.previous import Previous
from hevy_garmin_sync.workout import LoggedSet
from tests import fixtures
from tests.fixtures import hevy_deleted_event, hevy_logged_set, hevy_workout_event

JAN_1 = "2026-01-01T17:00:00+00:00"
JAN_8 = "2026-01-08T17:00:00+00:00"
JAN_10 = "2026-01-10T17:00:00+00:00"
JAN_12 = "2026-01-12T17:00:00+00:00"
# 60 kg for 8 at RPE 8: what `hevy_logged_set` logs.
SIXTY = LoggedSet(60.0, 8, 8.0)


def row(kilograms: float | None, reps: int | None, workout_id: str, start: str | None, **fields: Any) -> dict[str, Any]:
    """One logged set of the bench press, from the workout `workout_id`."""
    return fixtures.hevy_history_set(kilograms, reps, start, workout_id=workout_id, **fields)


class PreviousCase(unittest.TestCase):
    def setUp(self) -> None:
        self.api = fixtures.FakeHevyApi()
        # Two sessions: an older one, and on 10 January a warm-up and two working sets.
        self.api.history["T-BENCH"] = [
            row(50, 10, "w-old", JAN_1),
            row(40, 10, "w-last", JAN_10, set_type="warmup"),
            row(60, 6, "w-last", JAN_10, rpe=7),
            row(60, 5, "w-last", JAN_10, rpe=7.5),
        ]
        self.previous = Previous(hevy.Hevy("made-up-key", self.api), lambda: fixtures.NOW)  # type: ignore[arg-type]

    def history_reads(self, template_id: str = "T-BENCH") -> int:
        return sum(path == f"/exercise_history/{template_id}" for path, _ in self.api.requests)


class HistoryTest(PreviousCase):
    def test_the_first_ask_reads_a_year_of_history_and_gives_the_newest_sessions_working_sets(self) -> None:
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(60.0, 6, 7.0), LoggedSet(60.0, 5, 7.5)))
        (asked,) = [params for path, params in self.api.requests if path == "/exercise_history/T-BENCH"]
        self.assertEqual(
            asked,
            {"start_date": hevy._utc(fixtures.NOW - timedelta(days=365)), "end_date": hevy._utc(fixtures.NOW)},
        )

    def test_the_answer_is_kept_so_history_is_read_once(self) -> None:
        self.previous.sets("T-BENCH")
        self.previous.sets("T-BENCH")
        self.assertEqual(self.history_reads(), 1)

    def test_a_newer_session_of_warm_ups_alone_is_not_last_time(self) -> None:
        self.api.history["T-BENCH"].append(row(40, 10, "w-warm", JAN_12, set_type="warmup"))
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(60.0, 6, 7.0), LoggedSet(60.0, 5, 7.5)))

    def test_any_set_but_a_warm_up_is_a_working_set(self) -> None:
        self.api.history["T-BENCH"] = [
            row(60, 6, "w-1", JAN_1, set_type=kind) for kind in ("normal", "dropset", "failure", "warmup")
        ]
        self.assertEqual(len(self.previous.sets("T-BENCH")), 3)

    def test_an_exercise_with_no_history_has_none_and_is_not_asked_for_again(self) -> None:
        self.assertEqual(self.previous.sets("T-PLANK"), ())
        self.assertEqual(self.previous.sets("T-PLANK"), ())
        self.assertEqual(self.history_reads("T-PLANK"), 1)

    def test_a_set_keeps_its_time_and_distance_and_a_zero_or_null_is_none(self) -> None:
        self.api.history["T-BENCH"] = [
            row(None, 0, "w-1", JAN_1, rpe=None, duration_seconds=90, distance_meters=25),
            row(0, None, "w-1", JAN_1, rpe=0, duration_seconds=0, distance_meters=0),
        ]
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(seconds=90, meters=25.0), LoggedSet()))

    def test_a_session_with_no_start_counts_as_the_oldest(self) -> None:
        self.api.history["T-BENCH"] = [row(70, 3, "w-undated", None), row(50, 10, "w-old", JAN_1)]
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(50.0, 10, 8.0),))

    def test_an_exercise_with_no_template_id_reads_nothing(self) -> None:
        self.assertEqual(self.previous.sets(""), ())
        self.assertEqual(self.api.requests, [])


class EventsTest(PreviousCase):
    def setUp(self) -> None:
        super().setUp()
        self.previous.sets("T-BENCH")  # kept: w-last, 10 January

    def saved(self, workout_id: str, start: str, *sets: dict[str, Any], template_id: str = "T-BENCH") -> None:
        self.previous.update([hevy_workout_event(workout_id, template_id, "Made Up", list(sets) or None, start)])

    def test_a_newer_workout_becomes_last_time(self) -> None:
        self.saved("w-new", JAN_12, hevy_logged_set(type="warmup", weight_kg=40.0), hevy_logged_set())
        self.assertEqual(self.previous.sets("T-BENCH"), (SIXTY,))
        self.assertEqual(self.history_reads(), 1)

    def test_a_workout_that_starts_when_the_kept_one_did_becomes_last_time_too(self) -> None:
        self.saved("w-same", JAN_10)
        self.assertEqual(self.previous.sets("T-BENCH"), (SIXTY,))

    def test_an_older_workout_saved_now_is_not_last_time(self) -> None:
        self.saved("w-older", JAN_8)
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(60.0, 6, 7.0), LoggedSet(60.0, 5, 7.5)))

    def test_an_edit_of_the_kept_workout_replaces_its_sets_wherever_its_start_moved(self) -> None:
        self.saved("w-last", JAN_1, hevy_logged_set(reps=4))
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(60.0, 4, 8.0),))

    def test_the_kept_workout_without_the_exercise_any_more_has_its_history_read_again(self) -> None:
        for sets in ([hevy_logged_set(type="warmup")], []):
            with self.subTest(sets=sets):
                self.setUp()
                event = hevy_workout_event("w-last", "T-BENCH", "Made Up", start=JAN_10)
                if sets:
                    event["workout"]["exercises"][0]["sets"] = sets
                else:
                    event["workout"]["exercises"][0]["exercise_template_id"] = "T-PLANK"
                self.previous.update([event])
                self.api.history["T-BENCH"] = [row(50, 10, "w-old", JAN_1)]
                self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(50.0, 10, 8.0),))
                self.assertEqual(self.history_reads(), 2)

    def test_a_newer_workout_of_warm_ups_alone_changes_nothing(self) -> None:
        self.saved("w-new", JAN_12, hevy_logged_set(type="warmup"))
        self.assertEqual(len(self.previous.sets("T-BENCH")), 2)
        self.assertEqual(self.history_reads(), 1)

    def test_an_exercise_logged_twice_in_one_workout_lists_both_in_order(self) -> None:
        event = hevy_workout_event("w-new", "T-BENCH", "Made Up", [hevy_logged_set(reps=5)], JAN_12)
        exercises = event["workout"]["exercises"]
        exercises.append(exercises[0] | {"index": 1, "sets": [hevy_logged_set(reps=3)]})
        self.previous.update([event])
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(60.0, 5, 8.0), LoggedSet(60.0, 3, 8.0)))

    def test_an_exercise_with_no_last_session_takes_its_first(self) -> None:
        self.assertEqual(self.previous.sets("T-PLANK"), ())
        held = hevy_logged_set(weight_kg=None, reps=None, duration_seconds=45)
        self.saved("w-new", JAN_1, held, template_id="T-PLANK")
        self.assertEqual(self.previous.sets("T-PLANK"), (LoggedSet(rpe=8.0, seconds=45),))
        self.assertEqual(self.history_reads("T-PLANK"), 1)

    def test_an_exercise_not_asked_for_yet_is_left_to_its_history(self) -> None:
        self.api.history["T-PLANK"] = [row(None, None, "w-new", JAN_12, duration_seconds=45, rpe=None)]
        held = hevy_logged_set(weight_kg=None, reps=None, duration_seconds=60)
        self.saved("w-new", JAN_12, held, template_id="T-PLANK")
        self.assertEqual(self.history_reads("T-PLANK"), 0)
        self.assertEqual(self.previous.sets("T-PLANK"), (LoggedSet(seconds=45),))

    def test_a_workout_with_no_start_replaces_only_an_exercise_with_none(self) -> None:
        self.previous.sets("T-PLANK")
        event = hevy_workout_event("w-undated", "T-BENCH", "Made Up")
        event["workout"]["start_time"] = None
        plank = hevy_workout_event("w-undated", "T-PLANK", "Made Up")["workout"]["exercises"][0]
        event["workout"]["exercises"].append(plank)
        self.previous.update([event])
        self.assertEqual(len(self.previous.sets("T-BENCH")), 2)
        self.assertEqual(self.previous.sets("T-PLANK"), (SIXTY,))

    def test_a_deleted_workout_drops_every_exercise_kept_from_it(self) -> None:
        self.previous.sets("T-PLANK")
        self.saved("w-plank", JAN_12, template_id="T-PLANK")
        self.previous.sets("T-SQUAT")  # kept as none
        for deleted in (hevy_deleted_event("w-last"), {"type": "deleted", "workout": {"id": "w-last"}}):
            with self.subTest(deleted=deleted):
                reads = self.history_reads()
                self.previous.update([deleted])
                self.previous.sets("T-BENCH")
                self.previous.sets("T-PLANK")
                self.previous.sets("T-SQUAT")
                self.assertEqual(self.history_reads() - reads, 1)
                self.assertEqual((self.history_reads("T-PLANK"), self.history_reads("T-SQUAT")), (1, 1))

    def test_the_events_are_followed_oldest_first_as_hevy_lists_them_newest_first(self) -> None:
        first = hevy_workout_event("w-new", "T-BENCH", "Made Up", [hevy_logged_set(reps=5)], JAN_12)
        edited = hevy_workout_event("w-new", "T-BENCH", "Made Up", [hevy_logged_set(reps=6)], JAN_12)
        self.previous.update([edited, first])
        self.assertEqual(self.previous.sets("T-BENCH"), (LoggedSet(60.0, 6, 8.0),))
        self.previous.update([hevy_deleted_event("w-new"), edited])
        self.previous.sets("T-BENCH")
        self.assertEqual(self.history_reads(), 2)

    def test_an_event_of_another_kind_changes_nothing(self) -> None:
        self.previous.update([{"type": "made-up", "id": "w-last"}])
        self.assertEqual(len(self.previous.sets("T-BENCH")), 2)
        self.assertEqual(self.history_reads(), 1)


if __name__ == "__main__":
    unittest.main()
