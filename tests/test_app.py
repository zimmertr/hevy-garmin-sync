"""The process: startup checks, the poll loop, midnight, and what happens when a service fails (spec F-1, O-1)."""

import io
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

    def run_app(self, *steps: Step, **env: str) -> int:
        self.steps = list(steps)
        return app.App(
            config.load(self.env | env),
            hevy.Hevy("made-up-key", self.hevy_api),  # type: ignore[arg-type]
            self.garmin,
            fixtures.exercise_map(),
            hevy_private=self.hevy_private,
            wait=self.wait,
            clock=lambda: self.clock,
            utcnow=lambda: self.utc,
        ).run()

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

    def test_a_rejected_hevy_key_exits_with_the_fix(self) -> None:
        self.hevy_api.fail(401)
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(), 1)
        self.assertIn("Hevy rejected the app's credentials; check HEVY_API_KEY", logs.output[0])
        self.assertEqual(self.garmin_api.calls, [])

    def test_a_rejected_garmin_token_exits_with_the_fix(self) -> None:
        self.garmin_api.fail("get_user_profile", garminconnect.GarminConnectAuthenticationError("401"))
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(), 1)
        self.assertIn("Garmin rejected the app's credentials; run `login` again", logs.output[0])
        self.assertEqual(self.names(), [])

    def test_a_folder_setting_that_names_no_folder_exits(self) -> None:
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(INCLUDE_HEVY_FOLDERS="Legs"), 1)
        self.assertIn("INCLUDE_HEVY_FOLDERS names no Hevy folder: Legs", logs.output[0])

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
        self.assertIn("Hevy poll: 3 calls, 2 routines", "\n".join(logs.output))

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
        # Polled on every wake, whatever Garmin was doing: 8 wakes after the break, 2 calls each.
        self.assertEqual(len(self.hevy_api.requests), 16)
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

    def test_a_token_garmin_rejects_while_running_exits_one_with_the_fix(self) -> None:
        # O-1: exit at once, as at startup, so Kubernetes and Docker show the app as failing.
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(self.break_garmin(fixtures.garmin_error(401)), None, None), 1)
        self.assertIn("Garmin rejected the app's credentials; run `login` again", logs.output[-1])
        # The one poll wait before the break, and none after it: no retry.
        self.assertEqual(self.waits, [60])
        self.assertEqual(self.garmin_api.calls, ["upload_workout"])

    def test_a_garmin_rejection_at_any_call_of_a_sync_exits_one_and_makes_no_call_after_it(self) -> None:
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
                    self.assertEqual(self.run_app(None), 1)
                self.assertIn("Garmin rejected the app's credentials", logs.output[-1])
                self.assertEqual(self.garmin_api.calls[-1], method)
                self.assertEqual(self.waits, [])

    def test_a_hevy_key_rejected_while_running_exits_one_with_the_fix(self) -> None:
        def reject() -> None:
            self.hevy_api.fail(401)
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(reject, None), 1)
        self.assertIn("Hevy rejected the app's credentials; check HEVY_API_KEY", logs.output[-1])
        self.assertEqual(self.waits, [60])
        self.assertEqual(self.garmin_api.calls, [])

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
            self.hevy_api.events = [{"type": "updated", "workout": {"id": "made-up"}}]
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "INFO") as logs:
            self.run_app(log_upper)
        self.assertEqual(self.garmin_api.calls, ["update_workout", "push_workout_to_device"])
        self.assertIn("Hevy Trainer: Side Bend (Dumbbell): 40 lbs (up)", "\n".join(logs.output))

    def test_a_rejected_session_at_startup_exits_with_the_fix(self) -> None:
        self.end_the_session()
        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(), 1)
        self.assertIn("Hevy Trainer rejected the app's credentials; copy the auth2.0-token cookie", logs.output[0])
        self.assertIn("set HEVY_SESSION to it", logs.output[0])
        self.assertEqual(self.garmin_api.calls, [])

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

    def test_a_session_hevy_ends_while_running_exits_one_with_the_fix(self) -> None:
        def end() -> None:
            self.end_the_session()
            self.private_api.requests.clear()
            self.garmin_api.calls.clear()

        with self.assertLogs(LOGGER, "ERROR") as logs:
            self.assertEqual(self.run_app(end, None), 1)
        self.assertIn("Hevy Trainer rejected the app's credentials; copy the auth2.0-token cookie", logs.output[-1])
        self.assertIn("set HEVY_SESSION to it", logs.output[-1])
        # The session got its one refresh before the exit, and Garmin was not called.
        self.assertEqual(self.private_api.paths().count("auth/refresh_token"), 1)
        self.assertEqual(self.waits, [60])
        self.assertEqual(self.garmin_api.calls, [])
        self.assertIn(self.LOWER, self.names())

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
        # The workout events and one exercise's history from the public API; the program, three sets of
        # preferences and one page of logged workouts from the private one.
        self.assertIn("Hevy Trainer poll: 7 calls, 2 workouts", "\n".join(logs.output))


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


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.env = {"HEVY_API_KEY": "made-up-key", "DATA_DIR": folder.name}
        self.err = io.StringIO()
        self.handlers: dict[int, Callable[..., None]] = {}
        for patcher in (
            mock.patch.object(garminconnect, "Garmin", fixtures.FakeGarminApi),
            mock.patch.object(signal, "signal", lambda signum, handler: self.handlers.update({signum: handler})),
            mock.patch("hevy_garmin_sync.logs.setup"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

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


if __name__ == "__main__":
    unittest.main()
