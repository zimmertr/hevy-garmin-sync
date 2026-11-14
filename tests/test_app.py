"""The process: startup checks, the poll loop, midnight, and what happens when a service fails (spec F-1, O-1)."""

import io
import json
import signal
import tempfile
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import garminconnect
import requests

from hevy_garmin_sync import app, config, errors, garmin, hevy
from hevy_garmin_sync.exercises import GarminExercise
from hevy_garmin_sync.hevy_private import SESSION, HevyPrivate
from hevy_garmin_sync.store import Store
from tests import fixtures
from tests.fixtures import hevy_exercise, hevy_folder, hevy_routine, hevy_set, logged_set, logged_workout

Step = Callable[[], None] | None
LOGGER = "hevy_garmin_sync"


class AppCase(unittest.TestCase):
    """The app over a fake Hevy and a fake Garmin, woken by a script instead of by time.

    `run(step, step, ...)` lets the loop go round once per step plus once more:
    each step runs while the app waits, then the app is told to stop.
    """

    env: dict[str, str] = {"HEVY_API_KEY": "made-up-key", "TZ": "America/Los_Angeles"}

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.hevy_api = fixtures.FakeHevyApi()
        self.hevy_api.folders = [hevy_folder(42, "PPL")]
        self.hevy_api.routines = [hevy_routine("r-push", "Push", 42), hevy_routine("r-pull", "Pull", 42)]
        self.garmin_api = fixtures.FakeGarminApi()
        self.stopping = False
        pacing = fixtures.FakeClock()
        self.store = Store(Path(folder.name))
        self.hevy_private: HevyPrivate | None = None
        self.garmin = garmin.Garmin(
            self.garmin_api,  # type: ignore[arg-type]
            self.store,
            sleep=pacing.sleep,
            clock=pacing,
            stopping=lambda: self.stopping,
        )
        self.clock = 0.0
        self.utc = fixtures.NOW.astimezone(UTC)
        self.waits: list[float] = []
        self.steps: list[Step] = []
        self.nudged: list[None] = []  # each time the app was woken for a manual sync

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.clock += seconds
        self.utc += timedelta(seconds=seconds)
        if not self.steps:
            return True
        step = self.steps.pop(0)
        if step:
            step()
        return False

    def make_app(self, **env: str) -> app.App:
        loaded = config.load(self.env | env)
        self.app = app.App(
            loaded,
            hevy.Hevy("made-up-key", self.hevy_api),  # type: ignore[arg-type]
            self.garmin,
            fixtures.exercise_map(loaded.custom_exercises),
            hevy_private=self.hevy_private,
            wait=self.wait,
            nudge=lambda: self.nudged.append(None),
            clock=lambda: self.clock,
            utcnow=lambda: self.utc,
        )
        return self.app

    def run_app(self, *steps: Step, **env: str) -> int:
        self.steps = list(steps)
        return self.make_app(**env).run()

    def service(self, name: str) -> dict[str, object]:
        """One service as the status page shows it."""
        return next(s for s in self.app.status["services"] if s["name"] == name)

    def names(self) -> list[str]:
        return sorted(w["workoutName"] for w in self.garmin_api.workouts.values())

    def days(self) -> set[str]:
        return {e["calendarDate"] for e in self.garmin_api.entries.values()}

    def on_the_calendar(self) -> list[str]:
        ids = [e["workout"]["workoutId"] for e in self.garmin_api.entries.values()]
        return sorted(self.garmin_api.workouts[i]["workoutName"] for i in ids)


class StartupTest(AppCase):
    def test_the_first_run_puts_every_routine_in_garmin_and_on_today(self) -> None:
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.assertEqual(self.run_app(), 0)
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])
        self.assertEqual(self.days(), {fixtures.TODAY.isoformat()})
        text = "\n".join(logs.output)
        self.assertIn("Hevy routine folder: id 42, title 'PPL'", text)
        self.assertIn("Time zone: America/Los_Angeles (from TZ)", text)
        self.assertIn("Sync: created 2, updated 0, deleted 0, scheduled 2, unscheduled 0, failed 0", text)
        self.assertIn("Stopped", logs.output[-1])

    def test_a_rejected_hevy_key_stops_hevy_and_the_app_keeps_running_with_the_fix_on_the_page(self) -> None:
        # W-8: no exit and no restart loop; the page says what to fix.
        self.hevy_api.fail(401)
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(None), 0)
        self.assertIn("Hevy rejected the app's credentials; check HEVY_API_KEY", logs.output[0])
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(self.names(), [])
        self.assertEqual(self.service("Hevy")["state"], "rejected")
        self.assertIn("HEVY_API_KEY", str(self.service("Hevy")["reason"]))
        self.assertFalse(self.app.ready())

    def test_a_rejected_garmin_token_stops_garmin_and_the_app_keeps_running(self) -> None:
        self.garmin_api.fail("get_user_profile", garminconnect.GarminConnectAuthenticationError("401"))
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(None), 0)
        self.assertIn("Garmin rejected the app's credentials; run `login` again", logs.output[0])
        self.assertEqual(self.names(), [])
        self.assertEqual(self.garmin_api.calls, ["get_user_profile"])
        self.assertEqual(self.service("Garmin")["state"], "rejected")
        self.assertEqual(self.service("Hevy")["state"], "working")
        self.assertFalse(self.app.ready())

    def test_a_folder_setting_that_names_no_folder_exits(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(INCLUDE_HEVY_FOLDERS="Legs"), 1)
        self.assertIn("INCLUDE_HEVY_FOLDERS names no Hevy folder: Legs", logs.output[0])

    def test_custom_exercise_map_sets_a_custom_exercise_and_rewrites_its_workout_once(self) -> None:
        self.hevy_api.templates.append(
            fixtures.hevy_template(
                "T-MINE", "My Cable Raise", is_custom=True, primary_muscle_group="shoulders", equipment="cable"
            )
        )
        self.hevy_api.routines = [
            hevy_routine("r-arms", "Arms", 42, [hevy_exercise("T-MINE", "My Cable Raise", [hevy_set(reps=12)])])
        ]
        override = "My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE"
        runs = []
        for env in ({}, {"CUSTOM_EXERCISE_MAP": override}, {"CUSTOM_EXERCISE_MAP": override}):
            with self.assertLogs(LOGGER, "INFO") as logs:
                self.run_app(**env)
            (stored,) = self.garmin_api.workouts.values()
            runs.append((json.dumps(stored), "\n".join(logs.output)))
        self.assertIn('"exerciseName": "TOTAL_BODY"', runs[0][0])
        self.assertIn("is Garmin's TOTAL_BODY / TOTAL_BODY, by muscle group and equipment", runs[0][1])
        self.assertIn('"category": "LATERAL_RAISE", "exerciseName": "CABLE_FRONT_RAISE"', runs[1][0])
        self.assertIn("is Garmin's LATERAL_RAISE / CABLE_FRONT_RAISE, from CUSTOM_EXERCISE_MAP", runs[1][1])
        self.assertIn("Sync: created 0, updated 1,", runs[1][1])
        self.assertIn("Sync: created 0, updated 0,", runs[2][1])

    def test_an_outage_at_startup_is_waited_out_not_exited_on(self) -> None:
        self.hevy_api.fail(requests.ConnectionError("down"), 503)
        self.garmin_api.fail("get_user_profile", fixtures.garmin_error(500))
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(None, None, None), 0)
        self.assertEqual(self.waits[:3], [60, 120, 60])
        self.assertIn("Hevy can't be reached or is failing (ConnectionError)", logs.output[0])
        self.assertIn("Trying again in 1 min", logs.output[0])
        self.assertIn("Trying again in 2 min", logs.output[1])
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])

    def test_a_stop_during_that_wait_exits_cleanly(self) -> None:
        self.hevy_api.fail(503)
        with self.assertLogs(LOGGER, "ERROR"):
            self.assertEqual(self.run_app(), 0)
        self.assertEqual(self.garmin_api.calls, [])

    def test_with_no_tz_the_garmin_profiles_zone_is_used(self) -> None:
        self.env = {"HEVY_API_KEY": "made-up-key"}
        self.garmin_api.zone = "Europe/Berlin"
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app()
        self.assertIn("Time zone: Europe/Berlin (from the Garmin profile; set TZ to override)", "\n".join(logs.output))
        # 17:40 in Los Angeles is already tomorrow in Berlin.
        self.assertEqual(self.days(), {(fixtures.TODAY + timedelta(days=1)).isoformat()})

    def test_with_no_zone_anywhere_it_is_utc_and_says_so(self) -> None:
        self.env = {"HEVY_API_KEY": "made-up-key"}
        for zone in (None, "Not/AZone"):
            with self.subTest(zone=zone):
                self.garmin_api.zone = zone
                with self.assertLogs(LOGGER, "WARNING") as logs:
                    self.run_app()
                self.assertIn("Time zone: UTC", logs.output[0])


class PollTest(AppCase):
    def test_an_edit_in_hevy_reaches_garmin_on_the_next_poll(self) -> None:
        def edit() -> None:
            self.hevy_api.routines[0] = hevy_routine(
                "r-push", "Push", 42, [hevy_exercise("T-BENCH", "Bench Press (Barbell)", [hevy_set(reps=5)])]
            )
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(edit)
        self.assertEqual(self.garmin_api.calls, ["update_workout", "push_workout_to_device"])
        self.assertIn("Sync: created 0, updated 1", logs.output[-2])

    def test_a_poll_with_no_change_makes_no_garmin_call_and_logs_nothing(self) -> None:
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(self.garmin_api.calls.clear, None, None)
        self.assertEqual(self.garmin_api.calls, [])
        self.assertEqual(sum("Sync:" in line for line in logs.output), 1)
        self.assertEqual(self.waits, [60, 60, 60, 60])

    def test_the_poll_interval_is_the_configured_one(self) -> None:
        self.run_app(None, HEVY_POLL_INTERVAL_SECONDS="15")
        self.assertEqual(self.waits, [15, 15])

    def test_a_deleted_routine_leaves_garmin_after_two_polls(self) -> None:
        def delete_pull() -> None:
            self.hevy_api.routines.pop()

        self.run_app(delete_pull, None)
        self.assertEqual(self.names(), ["Hevy/PPL: Push"])

    def test_trainer_workouts_are_removed_while_trainer_is_off(self) -> None:
        self.garmin_api.workouts[7] = {
            "workoutId": 7,
            "workoutName": "Hevy/Trainer: Upper (C1-W1)",
            "description": "Synced from Hevy: https://github.com/zimmertr/hevy-garmin-sync\nHevy Trainer template: t-1",
        }
        self.run_app(None)
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])

    def test_each_poll_logs_its_hevy_call_count_at_debug(self) -> None:
        with self.assertLogs(LOGGER, "DEBUG") as logs:
            self.run_app()
        # The workout events, the folders, the routines, the exercise templates and the bench press's history.
        self.assertIn("Hevy poll: 5 calls, 2 routines", "\n".join(logs.output))

    def test_an_hour_with_no_change_gets_one_line_saying_so(self) -> None:
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(*[None] * 125)
        notes = [line for line in logs.output if "Nothing changed in the last hour" in line]
        self.assertEqual(len(notes), 2)
        self.assertIn("(60 polls)", notes[0])

    def test_a_stop_in_the_middle_of_a_sync_starts_no_new_write_and_exits_zero(self) -> None:
        def stop_after_one_write(*args: object) -> dict[str, int]:
            self.stopping = True
            return {"workoutId": 1}

        with mock.patch.object(self.garmin_api, "upload_workout", stop_after_one_write):
            self.assertEqual(self.run_app(None, None), 0)
        self.assertEqual(self.waits, [])
        self.assertEqual([c for c in self.garmin_api.calls if "schedule" in c or "push" in c], [])


class MidnightTest(AppCase):
    def test_the_wait_never_runs_past_local_midnight(self) -> None:
        self.utc = datetime(2026, 1, 16, 7, 59, 30, tzinfo=UTC)  # 23:59:30 in Los Angeles
        self.run_app(None)
        self.assertEqual(self.waits, [31, 60])

    def test_at_midnight_the_calendar_moves_to_the_new_day(self) -> None:
        self.utc = datetime(2026, 1, 16, 7, 59, 30, tzinfo=UTC)
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(None)
        self.assertEqual(self.days(), {"2026-01-16"})
        self.assertIn("scheduled 2, unscheduled 2", logs.output[-2])

    def test_the_wait_is_right_across_a_clock_change(self) -> None:
        # Clocks in Los Angeles go forward on 8 March 2026, so that day has 23 hours.
        self.utc = datetime(2026, 3, 8, 8, 0, 30, tzinfo=UTC)  # 00:00:30 PST
        self.run_app(HEVY_POLL_INTERVAL_SECONDS="86400")
        self.assertEqual(self.waits, [23 * 3600 - 30 + 1])

    def test_with_hevy_down_at_midnight_the_calendar_still_moves(self) -> None:
        self.utc = datetime(2026, 1, 16, 7, 59, 30, tzinfo=UTC)
        with self.assertLogs(LOGGER, "ERROR"):
            self.run_app(lambda: self.hevy_api.fail(503))
        self.assertEqual(self.days(), {"2026-01-16"})


class FailureTest(AppCase):
    def break_garmin(self, *errors_: BaseException) -> Callable[[], None]:
        def step() -> None:
            self.hevy_api.routines.append(hevy_routine("r-legs", "Legs", 42))
            self.garmin_api.fail("upload_workout", *errors_)
            self.garmin_api.calls.clear()
            self.hevy_api.requests.clear()

        return step

    def test_a_garmin_outage_is_logged_backed_off_and_followed_by_a_full_run(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.run_app(self.break_garmin(fixtures.garmin_error(503)), None)
        self.assertIn("Garmin can't be reached or is failing (API Error 503)", logs.output[0])
        self.assertIn("Trying again in 1 min", logs.output[0])
        # One failed write, then a full run a minute later: the list is read again and the job finished.
        self.assertEqual(self.garmin_api.calls[:3], ["upload_workout", "get_user_profile", "get_workouts"])
        self.assertEqual(self.names(), ["Hevy/PPL: Legs", "Hevy/PPL: Pull", "Hevy/PPL: Push"])

    def test_the_wait_doubles_while_garmin_stays_down_and_hevy_is_still_polled(self) -> None:
        down = [fixtures.garmin_error(503)] * 3
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(self.break_garmin(*down), *[None] * 7), 0)
        self.assertEqual([line.split("Trying again in ")[1] for line in logs.output], ["1 min.", "2 min.", "4 min."])
        # Polled on every wake, whatever Garmin was doing: 8 wakes after the break, 3 calls each (the workout
        # events, the folders and the routines).
        self.assertEqual(len(self.hevy_api.requests), 24)
        self.assertIn("Hevy/PPL: Legs", self.names())

    def test_a_garmin_rate_limit_waits_fifteen_minutes_first(self) -> None:
        limited = garminconnect.GarminConnectTooManyRequestsError("slow down")
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(self.break_garmin(limited), *[None] * 14), 0)
        self.assertIn("Garmin is rate limiting the app", logs.output[0])
        self.assertIn("Trying again in 15 min", logs.output[0])
        self.assertNotIn("Hevy/PPL: Legs", self.names())
        self.steps = []
        self.run_app(None)
        self.assertIn("Hevy/PPL: Legs", self.names())

    def test_a_garmin_rate_limit_asking_for_an_hour_is_waited_an_hour_past_the_cap(self) -> None:
        # TJ, 2026-11-10, #27: the service's wait wins over the 30 minute cap (O-1).
        limited = fixtures.garmin_error(429, headers={"Retry-After": "3600"})
        calls_at_the_hour: list[list[str]] = []

        def an_hour_on() -> None:
            calls_at_the_hour.append(list(self.garmin_api.calls))

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(self.break_garmin(limited), *[None] * 59, an_hour_on), 0)
        self.assertIn("Garmin is rate limiting the app and said how long to wait", logs.output[0])
        self.assertIn("Trying again in 60 min.", logs.output[0])
        self.assertEqual(calls_at_the_hour, [["upload_workout"]])
        self.assertIn("Hevy/PPL: Legs", self.names())

    def test_a_hevy_rate_limit_asking_for_two_minutes_leaves_hevy_alone_that_long(self) -> None:
        def limited() -> None:
            self.hevy_api.fail(fixtures.rate_limited("120"))
            self.hevy_api.requests.clear()

        reads: list[int] = []

        def note() -> None:
            reads.append(len(self.hevy_api.requests))

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(limited, note, note), 0)
        self.assertIn("Hevy is rate limiting the app and said how long to wait", logs.output[0])
        self.assertIn("Trying again in 2 min.", logs.output[0])
        # The 429 a minute after startup, nothing a minute later, and Hevy read again two minutes on.
        self.assertEqual(reads, [1, 1])
        self.assertGreater(len(self.hevy_api.requests), 1)

    def test_a_rate_limit_at_startup_is_waited_as_long_as_it_asks(self) -> None:
        self.hevy_api.fail(fixtures.rate_limited("30"))
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(HEVY_POLL_INTERVAL_SECONDS="10"), 0)
        self.assertIn("Trying again in 30 s.", logs.output[0])
        self.assertEqual(self.waits, [30])

    def test_a_token_garmin_rejects_while_running_stops_every_garmin_call_after_it(self) -> None:
        # W-8: waiting can't fix a dead token, so Garmin is left alone until the fix and a restart.
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(self.break_garmin(fixtures.garmin_error(401)), None, None), 0)
        self.assertIn("Garmin rejected the app's credentials; run `login` again", logs.output[-1])
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(self.garmin_api.calls, ["upload_workout"])
        self.assertEqual(self.service("Garmin")["state"], "rejected")

    def test_a_garmin_rejection_at_any_call_of_a_sync_makes_no_call_after_it(self) -> None:
        for method in (
            "get_workouts",
            "upload_workout",
            "schedule_workout",
            "push_workout_to_device",
            "get_scheduled_workouts_by_period",
        ):
            with self.subTest(method=method):
                self.setUp()
                self.garmin_api.fail(method, garminconnect.GarminConnectAuthenticationError("401"))
                with self.assertLogs(LOGGER, "ERROR") as logs:
                    self.assertEqual(self.run_app(None), 0)
                self.assertIn("Garmin rejected the app's credentials", logs.output[-1])
                self.assertEqual(self.garmin_api.calls[-1], method)

    def test_a_hevy_key_rejected_while_running_stops_hevy_and_leaves_garmin_as_it_is(self) -> None:
        def reject() -> None:
            self.hevy_api.fail(401)
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(reject, None, None), 0)
        self.assertIn("Hevy rejected the app's credentials; check HEVY_API_KEY", logs.output[-1])
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(self.garmin_api.calls, [])
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])

    def test_a_hevy_outage_is_logged_and_garmin_is_left_alone(self) -> None:
        def down() -> None:
            self.hevy_api.fail(503, 429)
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(down, None, None, None), 0)
        self.assertIn("Hevy can't be reached or is failing (HTTP 503", logs.output[0])
        self.assertIn("Hevy is rate limiting the app", logs.output[1])
        self.assertEqual(self.garmin_api.calls, [])

    def test_hevy_refusing_a_request_is_said_plainly(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.run_app(lambda: self.hevy_api.fail(400))
        self.assertIn("Hevy refused a request (HTTP 400", logs.output[0])

    def test_a_bug_while_syncing_is_logged_with_its_traceback_and_does_not_end_the_process(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(self.break_garmin(RuntimeError("a bug")), None), 0)
        self.assertIn("Unexpected error while syncing", logs.output[0])
        self.assertIn("RuntimeError: a bug", logs.output[0])
        self.assertIn("Hevy/PPL: Legs", self.names())

    def test_a_hevy_reply_in_an_unexpected_shape_does_not_end_the_process_either(self) -> None:
        def odd() -> None:
            self.hevy_api.routines.append({"title": "a routine with no id"})

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(odd, None), 0)
        self.assertIn("Unexpected error while reading Hevy", logs.output[0])
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])


class TrainerTest(AppCase):
    """With HEVY_SESSION set, Hevy Trainer's workouts sync beside the routines (spec section 6)."""

    LOWER, UPPER = "Hevy/Trainer: Lower (C2-W2)", "Hevy/Trainer: Upper (C2-W2)"
    INPUTS = ["v2/user_preferences", "hevy_trainer/user_preferences", "exercise_template_units", "user_workouts_paged"]

    def setUp(self) -> None:
        super().setUp()
        self.utc = fixtures.PROGRAM_WEEK_8.astimezone(UTC)
        self.hevy_api.templates += fixtures.trainer_exercise_templates()
        self.private_api = fixtures.FakeHevyPrivateApi()
        upper = fixtures.trainer_template("t-upper", "upper_2x_a", [fixtures.trainer_exercise("T-SIDE-BEND")])
        # Lower was logged on the Tuesday of this week, so Hevy says Upper is next.
        self.private_api.program = fixtures.trainer_program([fixtures.lower_template(), upper], next_workout_index=1)
        self.private_api.workouts = [fixtures.logged_lower(fixtures.PROGRAM_WEEK_8 - timedelta(days=3))]
        self.hevy_private = HevyPrivate(
            fixtures.HEVY_SESSION_TOKENS,
            self.store,
            self.private_api,  # type: ignore[arg-type]
            utcnow=lambda: self.utc,
        )

    def end_the_session(self) -> None:
        """Hevy no longer knows the access token or the refresh token."""
        self.private_api.access = self.private_api.refresh = "made-up-and-gone"

    def test_trainers_workouts_sync_beside_the_routines(self) -> None:
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.assertEqual(self.run_app(), 0)
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push", self.LOWER, self.UPPER])
        self.assertIn("Sync: created 4, updated 0, deleted 0, scheduled 3", "\n".join(logs.output))

    def test_only_the_trainer_workout_hevy_says_is_next_is_on_the_calendar_and_both_are_in_garmin(self) -> None:
        self.run_app()
        self.assertEqual(self.on_the_calendar(), ["Hevy/PPL: Pull", "Hevy/PPL: Push", self.UPPER])
        self.assertIn(self.LOWER, self.names())

    def test_when_hevys_next_workout_changes_the_calendar_follows_on_that_poll(self) -> None:
        def reorder() -> None:
            assert self.private_api.program is not None
            self.private_api.program["next_workout_index"] = 0
            self.garmin_api.calls.clear()

        self.run_app(reorder)
        self.assertEqual(self.garmin_api.calls, ["unschedule_workout", "schedule_workout"])
        self.assertEqual(self.on_the_calendar(), ["Hevy/PPL: Pull", "Hevy/PPL: Push", self.LOWER])
        self.assertEqual(self.days(), {fixtures.PROGRAM_WEEK_8.date().isoformat()})
        self.assertEqual(len(self.garmin_api.pushed), 4)

    def test_on_the_first_weekday_the_names_move_to_the_new_week_and_the_next_workout_is_on_the_new_day(self) -> None:
        self.utc = datetime(2026, 11, 9, 7, 59, 30, tzinfo=UTC)  # 23:59:30 on Sunday in Los Angeles
        self.run_app(None)
        lower, upper = "Hevy/Trainer: Lower (C2-W3)", "Hevy/Trainer: Upper (C2-W3)"
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push", lower, upper])
        self.assertEqual(self.on_the_calendar(), ["Hevy/PPL: Pull", "Hevy/PPL: Push", upper])
        self.assertEqual(self.days(), {"2026-11-09"})

    def test_a_logged_workout_changes_the_weights_in_garmin_on_the_next_poll(self) -> None:
        def log_upper() -> None:
            self.private_api.workouts.append(
                logged_workout("t-upper", fixtures.PROGRAM_WEEK_8, {"T-SIDE-BEND": [logged_set(35, 12)] * 3})
            )
            self.hevy_api.events = [fixtures.hevy_workout_event("made-up", "T-SIDE-BEND", "Side Bend (Dumbbell)")]
            self.garmin_api.calls.clear()

        # Without last time's sets, so the weight is all that changes.
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(log_upper, ENABLE_PREVIOUS_VALUES="false")
        self.assertEqual(self.garmin_api.calls, ["update_workout", "push_workout_to_device"])
        self.assertIn("Hevy Trainer: Side Bend (Dumbbell): 40 lbs (up)", "\n".join(logs.output))

    def test_a_workout_logged_while_trainer_waits_after_a_failure_is_still_acted_on(self) -> None:
        def down() -> None:
            self.private_api.fail(503)

        def logged() -> None:
            self.hevy_api.events = [fixtures.hevy_workout_event("made-up", "T-SIDE-BEND", "Side Bend (Dumbbell)")]

        def quiet() -> None:
            self.hevy_api.events = []
            self.private_api.requests.clear()

        with self.assertLogs(LOGGER, "ERROR"):
            self.run_app(down, logged, quiet, None, None, HEVY_POLL_INTERVAL_SECONDS="15")
        # Trainer failed at 15 s and was left alone until 75 s; the workout logged at 30 s was not lost.
        self.assertEqual(self.private_api.paths(), ["hevy_trainer/v3/program", *self.INPUTS])

    def test_the_workout_events_are_read_once_a_poll_for_trainer_and_last_times_sets_alike(self) -> None:
        self.run_app(None)
        events = [path for path, _ in self.hevy_api.requests if path == "/workouts/events"]
        self.assertEqual(len(events), 2)

    def test_a_rejected_session_at_startup_stops_only_trainer_and_routines_still_sync(self) -> None:
        self.end_the_session()
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(), 0)
        self.assertIn("Hevy Trainer rejected the app's credentials; copy the auth2.0-token cookie", logs.output[0])
        self.assertIn("set HEVY_SESSION to it", logs.output[0])
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])
        self.assertEqual(self.service("Hevy Trainer")["state"], "rejected")

    def test_an_outage_of_hevys_private_api_at_startup_is_waited_out(self) -> None:
        self.private_api.fail(503)
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(None), 0)
        self.assertIn("Hevy Trainer can't be reached or is failing (HTTP 503", logs.output[0])
        self.assertEqual(self.waits[0], 60)
        self.assertIn(self.UPPER, self.names())

    def test_while_trainer_fails_routines_keep_syncing_and_trainers_workouts_stay(self) -> None:
        def down() -> None:
            self.private_api.fail(503)
            self.hevy_api.routines.append(hevy_routine("r-legs", "Legs", 42))
            self.private_api.requests.clear()

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(down, *[None] * 4, HEVY_POLL_INTERVAL_SECONDS="15"), 0)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Hevy Trainer can't be reached or is failing", logs.output[0])
        self.assertIn("Trying again in 1 min", logs.output[0])
        self.assertEqual(self.names(), ["Hevy/PPL: Legs", "Hevy/PPL: Pull", "Hevy/PPL: Push", self.LOWER, self.UPPER])
        # Asked at the poll that failed and a minute later, not on the three polls in between.
        self.assertEqual(self.private_api.paths().count("hevy_trainer/v3/program"), 2)

    def test_a_session_hevy_ends_while_running_stops_trainer_and_keeps_its_workouts(self) -> None:
        def end() -> None:
            self.end_the_session()
            self.private_api.requests.clear()
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(end, None), 0)
        self.assertIn(self.LOWER, self.names())
        self.assertNotIn("delete_workout", self.garmin_api.calls)
        self.assertIn("Hevy Trainer rejected the app's credentials; copy the auth2.0-token cookie", logs.output[-1])
        self.assertIn("set HEVY_SESSION to it", logs.output[-1])
        # The session got its one refresh, and was not tried again on the next poll.
        self.assertEqual(self.private_api.paths().count("auth/refresh_token"), 1)
        self.assertEqual(self.garmin_api.calls, [])

    def test_a_rate_limit_from_hevys_private_api_does_not_exit(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(lambda: self.private_api.fail(429), None), 0)
        self.assertIn("Hevy Trainer is rate limiting the app", logs.output[0])

    def test_a_program_in_an_unexpected_shape_does_not_end_the_process(self) -> None:
        def odd() -> None:
            assert self.private_api.program is not None
            self.private_api.program["templates"] = "not a list of workouts"

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(odd, None), 0)
        self.assertIn("Unexpected error while reading Hevy Trainer", logs.output[0])
        self.assertIn("AttributeError", logs.output[0])
        self.assertIn(self.LOWER, self.names())

    def test_a_program_that_is_deleted_takes_its_workouts_out_of_garmin(self) -> None:
        def delete_program() -> None:
            self.private_api.program = None

        self.run_app(delete_program, None)
        self.assertEqual(self.names(), ["Hevy/PPL: Pull", "Hevy/PPL: Push"])

    def test_each_poll_logs_trainers_hevy_call_count_at_debug(self) -> None:
        with self.assertLogs(LOGGER, "DEBUG") as logs:
            self.run_app()
        # From the public API, the history of the four exercises new to last time's sets and of one exercise new
        # to its workout; the program, three sets of preferences and one page of logged workouts from the private
        # one. The workout events count in the Hevy poll's line.
        self.assertIn("Hevy Trainer poll: 10 calls, 2 workouts", "\n".join(logs.output))


class PreviousTest(AppCase):
    """Last time's working sets for the status page, kept current by the workout events (#3)."""

    def setUp(self) -> None:
        super().setUp()
        self.hevy_api.history["T-BENCH"] = [fixtures.hevy_history_set(60, 8, "2026-01-10T17:00:00+00:00")]

    def notes(self) -> set[str | None]:
        """Every set's note in Garmin, from the repeat group each routine's three bench sets make."""
        groups = (w["workoutSegments"][0]["workoutSteps"][0] for w in self.garmin_api.workouts.values())
        return {group["workoutSteps"][0].get("description") for group in groups}

    def events_asked(self) -> list[str]:
        return [params["since"] for path, params in self.hevy_api.requests if path == "/workouts/events"]

    def test_a_saved_workout_changes_last_times_sets_but_no_note_so_garmin_is_left_alone(self) -> None:
        before: list[set[str | None]] = []
        lasts: list[set[tuple[Any, ...]]] = []

        def last_sets() -> set[tuple[Any, ...]]:
            return {e.previous for plans in self.app._plans or [] for w in plans.workouts for e in w.exercises}

        def save() -> None:
            sets = [fixtures.hevy_logged_set(weight_kg=62.5, reps=6), fixtures.hevy_logged_set(weight_kg=62.5, reps=5)]
            self.hevy_api.events = [fixtures.hevy_workout_event("w-new", "T-BENCH", "Bench Press (Barbell)", sets)]
            before.append(self.notes())
            lasts.append(last_sets())
            self.garmin_api.calls.clear()

        self.run_app(save)
        self.assertEqual(self.notes(), before[0])
        self.assertNotEqual(last_sets(), lasts[0])
        self.assertEqual(self.garmin_api.calls, [])
        # One history read, at startup; the events did the rest.
        self.assertEqual(sum(path.startswith("/exercise_history/") for path, _ in self.hevy_api.requests), 1)

    def test_a_saved_workout_that_changes_no_note_makes_no_garmin_call(self) -> None:
        def save() -> None:
            self.hevy_api.events = [fixtures.hevy_workout_event("w-new", "T-PLANK", "Plank")]
            self.garmin_api.calls.clear()

        self.run_app(save)
        self.assertEqual(self.garmin_api.calls, [])

    def test_the_events_are_asked_for_since_startup_and_then_since_the_poll_before(self) -> None:
        started = self.utc
        self.run_app(None, None)
        minute = hevy._utc(started + timedelta(seconds=60))
        self.assertEqual(self.events_asked(), [hevy._utc(started), hevy._utc(started), minute])

    def test_a_failed_events_read_is_waited_out_and_asked_again_from_where_it_was(self) -> None:
        started = self.utc
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.run_app(None, lambda: self.hevy_api.fail(503), None)
        self.assertIn("Hevy can't be reached or is failing (HTTP 503", logs.output[0])
        # The read two minutes on failed, so the one a minute after it asks from the same instant.
        minute = hevy._utc(started + timedelta(seconds=60))
        self.assertEqual(self.events_asked(), [hevy._utc(started), hevy._utc(started), minute, minute])

    def test_with_it_off_the_notes_are_as_before_and_no_history_or_event_is_read(self) -> None:
        self.run_app(None, ENABLE_PREVIOUS_VALUES="false")
        self.assertEqual(self.notes(), {None})
        asked = {path for path, _ in self.hevy_api.requests}
        self.assertEqual(asked, {"/routine_folders", "/routines", "/exercise_templates"})


class ManualSyncTest(AppCase):
    """Sync now, Force sync and the `sync` command, through the one door the server uses (W-3, W-4)."""

    def ask(self, force: bool = False, answers: list[tuple[str, int]] | None = None) -> Callable[[], None]:
        def step() -> None:
            answer = self.app.requests.ask(force)
            if answers is not None:
                answers.append(answer)
            self.garmin_api.calls.clear()

        return step

    def test_a_sync_sends_every_workout_to_the_watch_again_and_rewrites_none(self) -> None:
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(self.ask())
        self.assertEqual(self.nudged, [None])
        self.assertIn("Manual sync asked for", "\n".join(logs.output))
        # A full run: the list and the calendar read again, nothing rewritten, both sent to the watch.
        self.assertNotIn("update_workout", self.garmin_api.calls)
        self.assertEqual(self.garmin_api.calls.count("push_workout_to_device"), 2)
        self.assertIn("get_workouts", self.garmin_api.calls)
        self.assertEqual(self.app.status["sync"]["state"], "idle")
        self.assertIsNotNone(self.app.status["sync"]["last_ended"])
        self.assertEqual(self.app.status["sync"]["last_counts"]["updated"], 0)

    def test_a_forced_sync_rewrites_every_workout_in_place(self) -> None:
        before: list[list[int]] = []

        def ask() -> None:
            before.append(sorted(self.garmin_api.workouts))
            self.ask(force=True)()

        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(ask)
        self.assertIn("(forced: every workout is rewritten)", "\n".join(logs.output))
        self.assertEqual(self.garmin_api.calls.count("update_workout"), 2)
        self.assertNotIn("upload_workout", self.garmin_api.calls)
        # In place: each keeps its Garmin id, and so its calendar entry.
        self.assertEqual(before, [sorted(self.garmin_api.workouts)])
        self.assertNotIn("unschedule_workout", self.garmin_api.calls)
        self.assertEqual(self.app.status["sync"]["last_counts"]["updated"], 2)

    def test_a_request_within_a_minute_of_the_last_is_refused_with_the_seconds_left(self) -> None:
        answers: list[tuple[str, int]] = []
        self.run_app(self.ask(answers=answers), self.ask(answers=answers), HEVY_POLL_INTERVAL_SECONDS="20")
        # Asked at 20 s and run at once; asked again at 40 s, 20 s after it ended.
        self.assertEqual(answers, [("started", 0), ("wait", 40)])

    def test_a_request_while_one_waits_joins_it_and_a_force_still_counts(self) -> None:
        answers: list[tuple[str, int]] = []

        def twice() -> None:
            answers.append(self.app.requests.ask(False))
            answers.append(self.app.requests.ask(True))
            self.garmin_api.calls.clear()

        self.run_app(twice)
        self.assertEqual(answers, [("started", 0), ("joined", 0)])
        self.assertEqual(self.garmin_api.calls.count("update_workout"), 2)

    def test_a_sync_asked_for_during_garmins_wait_runs_only_when_the_wait_ends(self) -> None:
        def down_then_ask() -> None:
            self.garmin_api.fail("upload_workout", fixtures.garmin_error(503))
            self.hevy_api.routines.append(hevy_routine("r-legs", "Legs", 42))

        states: list[str] = []

        def ask() -> None:
            self.app.requests.ask(False)
            self.garmin_api.calls.clear()

        def look() -> None:
            states.append(self.app.status["sync"]["state"])

        with self.assertLogs(LOGGER, "ERROR"):
            # Garmin fails at the first poll and is left alone for a minute; the request at 15 s waits for it.
            self.run_app(down_then_ask, ask, look, None, None, None, HEVY_POLL_INTERVAL_SECONDS="15")
        self.assertEqual(states, ["waiting"])
        self.assertIn("push_workout_to_device", self.garmin_api.calls)
        self.assertEqual(self.app.status["sync"]["state"], "idle")

    def test_a_sync_asked_for_while_garmins_sign_in_is_rejected_ends_at_once(self) -> None:
        self.garmin_api.fail("get_user_profile", garminconnect.GarminConnectAuthenticationError("401"))
        answers: list[tuple[str, int]] = []
        with self.assertLogs(LOGGER, "ERROR"):
            self.run_app(self.ask(answers=answers), None)
        self.assertEqual(self.app.status["sync"]["state"], "idle")
        self.assertEqual(self.garmin_api.calls, [])

    def test_a_manual_sync_has_trainer_read_its_inputs_again_and_force_reads_last_times_sets_again(self) -> None:
        trainer = TrainerTest()
        trainer.setUp()
        trainer.hevy_api.history["T-SIDE-BEND"] = [fixtures.hevy_history_set(15, 12, "2026-01-10T17:00:00+00:00")]

        def ask() -> None:
            trainer.app.requests.ask(True)
            trainer.private_api.requests.clear()
            trainer.hevy_api.requests.clear()

        trainer.run_app(ask)
        self.assertEqual([p for p in trainer.private_api.paths() if p in TrainerTest.INPUTS], TrainerTest.INPUTS)
        self.assertTrue(any(path.startswith("/exercise_history/") for path, _ in trainer.hevy_api.requests))

    def test_the_loop_is_alive_while_it_waits_and_not_once_it_is_overdue(self) -> None:
        seen: list[bool] = []

        def look() -> None:
            seen.append(self.app.alive())
            self.clock += 10_000
            seen.append(self.app.alive())

        self.run_app(look)
        self.assertEqual(seen, [True, False])

    def test_the_status_lists_each_workout_with_its_garmin_id_and_today(self) -> None:
        self.run_app()
        workouts = self.app.status["workouts"]
        self.assertEqual([w["title"] for w in workouts], ["Push", "Pull"])
        self.assertEqual({w["folder"] for w in workouts}, {"PPL"})
        self.assertTrue(all(w["garmin_id"] for w in workouts))
        self.assertEqual({w["scheduled"] for w in workouts}, {fixtures.TODAY.isoformat()})
        self.assertEqual(self.app.status["settings"]["HEVY_API_KEY"], "set")
        self.assertNotIn("made-up-key", json.dumps(self.app.status))


class RequestsTest(unittest.TestCase):
    def test_a_force_pressed_once_a_sync_is_running_joins_it_and_leaves_it_as_it_is(self) -> None:
        requests = app.Requests(lambda: 0.0, lambda: None)
        requests.ask(False)
        requests.begin()
        self.assertEqual(requests.ask(True), ("joined", 0))
        self.assertFalse(requests.force)  # the run already chose what to write


class BackoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.backoff = app.Backoff(lambda: self.now, rate_limited=900)

    def test_it_starts_at_a_minute_doubles_and_stops_at_thirty(self) -> None:
        waits = [self.backoff.failed(errors.Unavailable()) for _ in range(7)]
        self.assertEqual(waits, [60, 120, 240, 480, 960, 1800, 1800])

    def test_it_is_ready_again_once_the_wait_is_over_or_the_service_answers(self) -> None:
        self.assertTrue(self.backoff.ready())
        self.backoff.failed(errors.Unavailable())
        self.assertFalse(self.backoff.ready())
        self.now = 60
        self.assertTrue(self.backoff.ready())
        self.backoff.failed(errors.Unavailable())
        self.backoff.succeeded()
        self.assertTrue(self.backoff.ready())
        self.assertEqual(self.backoff.failed(errors.Unavailable()), 60)

    def test_a_rate_limit_waits_at_least_fifteen_minutes(self) -> None:
        self.assertEqual(self.backoff.failed(errors.RateLimited()), 900)
        self.assertEqual(self.backoff.failed(errors.RateLimited()), 1800)
        self.backoff.succeeded()
        self.backoff.failed(errors.Unavailable())
        self.assertEqual(self.backoff.failed(errors.RateLimited()), 900)

    def test_a_rate_limit_that_says_how_long_is_waited_that_long_even_past_thirty_minutes(self) -> None:
        # TJ, 2026-11-10, #27: the service's wait wins over the app's own, shorter or longer.
        self.assertEqual(self.backoff.failed(errors.RateLimited(retry_after=120)), 120)
        self.assertEqual(self.backoff.failed(errors.RateLimited(retry_after=3600)), 3600)
        self.now = 3599
        self.assertFalse(self.backoff.ready())
        self.now = 3600
        self.assertTrue(self.backoff.ready())

    def test_a_rate_limit_asking_for_less_than_the_shortest_wait_gets_the_shortest(self) -> None:
        backoff = app.Backoff(lambda: self.now, shortest=45)
        self.assertEqual(backoff.failed(errors.RateLimited(retry_after=0)), 45)


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.env = {"HEVY_API_KEY": "made-up-key", "DATA_DIR": folder.name}
        self.err = io.StringIO()
        self.handlers: dict[int, Callable[..., None]] = {}
        # No socket in a test: the server is started and shut down as a fake (server.py has its own tests).
        self.start = mock.patch("hevy_garmin_sync.server.start")
        for patcher in (
            mock.patch.object(garminconnect, "Garmin", fixtures.FakeGarminApi),
            mock.patch.object(signal, "signal", lambda signum, handler: self.handlers.update({signum: handler})),
            mock.patch("hevy_garmin_sync.logs.setup"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = self.start.start()
        self.addCleanup(self.start.stop)

    def test_the_status_page_is_served_on_http_port_while_the_app_runs(self) -> None:
        env = self.env | {"GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS), "HTTP_PORT": "9090"}
        with (
            mock.patch.object(app.App, "run", return_value=0),
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()),
            self.assertLogs(LOGGER, "INFO"),
        ):
            self.assertEqual(app.main(env, self.err), 0)
        port, served, _ = self.server.call_args.args
        self.assertEqual(port, 9090)
        self.assertIsInstance(served, app.App)
        self.server.return_value.shutdown.assert_called_once_with()
        self.server.return_value.server_close.assert_called_once_with()

    def test_bad_configuration_exits_one_with_a_plain_message(self) -> None:
        self.assertEqual(app.main({}, self.err), 1)
        self.assertEqual(self.err.getvalue().count("\n"), 1)
        self.assertIn("hevy-garmin-sync: HEVY_API_KEY is required", self.err.getvalue())

    def test_no_garmin_token_anywhere_exits_one(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(app.main(self.env, self.err), 1)
        self.assertIn("GARMIN_TOKEN is not set", logs.output[0])

    def test_it_logs_the_version_and_configuration_then_runs_the_app(self) -> None:
        env = self.env | {"GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS)}
        with (
            mock.patch.object(app.App, "run", return_value=0) as run,
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()),
            self.assertLogs(LOGGER, "INFO") as logs,
        ):
            self.assertEqual(app.main(env, self.err), 0)
        run.assert_called_once_with()
        self.assertIn("hevy-garmin-sync ", logs.output[0])
        self.assertIn("HEVY_API_KEY: set", logs.output[1])
        self.assertNotIn("made-up-key", "\n".join(logs.output))

    def test_custom_exercise_map_reaches_the_map_and_only_its_count_is_logged(self) -> None:
        env = self.env | {
            "GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS),
            "CUSTOM_EXERCISE_MAP": "My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE",
        }
        with (
            mock.patch.object(app.App, "run", return_value=0),
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()) as load,
            self.assertLogs(LOGGER, "INFO") as logs,
        ):
            self.assertEqual(app.main(env, self.err), 0)
        wanted = {"My Cable Raise": GarminExercise("LATERAL_RAISE", "CABLE_FRONT_RAISE")}
        load.assert_called_once_with(overrides=wanted)
        self.assertIn("CUSTOM_EXERCISE_MAP: set (1 entry)", "\n".join(logs.output))
        self.assertNotIn("My Cable Raise", "\n".join(logs.output))

    def test_a_custom_exercise_map_pair_garmin_lacks_exits_one_before_any_sign_in(self) -> None:
        env = self.env | {"CUSTOM_EXERCISE_MAP": "My Cable Raise=LATERAL_RAISE/CABLE_SIDE_RAISE"}
        self.assertEqual(app.main(env, self.err), 1)
        self.assertIn(
            "hevy-garmin-sync: CUSTOM_EXERCISE_MAP names LATERAL_RAISE/CABLE_SIDE_RAISE, which Garmin doesn't have",
            self.err.getvalue(),
        )

    def test_with_hevy_session_set_the_session_is_stored_for_hevy_trainer(self) -> None:
        env = self.env | {
            "GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS),
            "HEVY_SESSION": fixtures.HEVY_SESSION_COOKIE,
        }
        with (
            mock.patch.object(app.App, "run", return_value=0),
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()),
            mock.patch.object(app, "Trainer") as trainer,
        ):
            self.assertEqual(app.main(env, self.err), 0)
        trainer.assert_called_once()
        self.assertIn("hevy-access-1", Store(Path(self.env["DATA_DIR"])).read(SESSION) or "")

    def test_a_hevy_session_that_is_not_the_cookie_exits_one(self) -> None:
        env = self.env | {"GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS), "HEVY_SESSION": "not-it"}
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(app.main(env, self.err), 1)
        self.assertIn("HEVY_SESSION is not the auth2.0-token cookie", logs.output[0])

    def test_with_hevy_session_unset_a_stored_session_is_removed(self) -> None:
        store = Store(Path(self.env["DATA_DIR"]))
        HevyPrivate.open(fixtures.HEVY_SESSION_COOKIE, store)
        env = self.env | {"GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS)}
        with (
            mock.patch.object(app.App, "run", return_value=0),
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()),
            mock.patch.object(app, "Trainer") as trainer,
        ):
            self.assertEqual(app.main(env, self.err), 0)
        trainer.assert_not_called()
        self.assertEqual(sorted(p.name for p in store.root.iterdir() if "hevy" in p.name), [])

    def test_sigterm_and_sigint_ask_the_app_to_stop(self) -> None:
        env = self.env | {"GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS)}
        waited: list[bool] = []

        def run(self: app.App) -> int:
            waited.append(self._wait(0))
            for handler in list(handlers.values()):
                handler(signal.SIGTERM, None)
            waited.append(self._wait(0))
            return 0

        handlers = self.handlers
        with (
            mock.patch.object(app.App, "run", run),
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()),
        ):
            app.main(env, self.err)
        self.assertEqual(sorted(self.handlers), sorted([signal.SIGTERM, signal.SIGINT]))
        self.assertEqual(waited, [False, True])

    def test_a_manual_sync_ends_the_wait_early_without_stopping_the_app(self) -> None:
        env = self.env | {"GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS)}
        waited: list[bool] = []

        def run(self: app.App) -> int:
            self.requests.ask(False)
            waited.append(self._wait(3600))  # woken at once, or this test would hang for an hour
            return 0

        with (
            mock.patch.object(app.App, "run", run),
            mock.patch("hevy_garmin_sync.exercises.ExerciseMap.load", return_value=fixtures.exercise_map()),
        ):
            app.main(env, self.err)
        self.assertEqual(waited, [False])


if __name__ == "__main__":
    unittest.main()
