"""scripts/live_check.py: the one run by hand for #22, #24 and #6, over the fakes, never the network."""

import io
import json
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest import mock

import garminconnect

from hevy_garmin_sync import garmin, workout
from hevy_garmin_sync.store import Store
from scripts import live_check as lc
from tests import fixtures
from tests.fixtures import hevy_exercise, hevy_folder, hevy_routine, hevy_set, trainer_program, trainer_template

API_KEY = "made-up-key"
TOKEN = garmin.encode_token(fixtures.GARMIN_TOKENS)
# Every value the fakes hold that must never reach the output or the saved file.
SECRETS = (
    API_KEY,
    fixtures.HEVY_SESSION_COOKIE,
    "hevy-access-1",
    "hevy-refresh-1",
    TOKEN,
    "access-1",
    "someone",
    "My Own Folder",
    "My Own Routine",
    "r-mine",
    "T-BENCH",
    "Bench Press",
    "t-upper",
    "upper_2x_a",
    "A1B2-C3D4",
)


class LiveCheckCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name) / "live-check"
        self.store = Store(self.folder)
        self.hevy_api = fixtures.FakeHevyApi()
        self.hevy_api.folders = [hevy_folder(42, "My Own Folder")]
        self.hevy_api.routines = [
            hevy_routine("r-mine", "My Own Routine", 42, [hevy_exercise("T-BENCH", "Bench Press", [hevy_set(reps=8)])])
        ]
        self.private_api = fixtures.FakeHevyPrivateApi()
        self.private_api.units = {"A1B2-C3D4": {"unit": "kg"}}
        self.private_api.program = trainer_program(
            [trainer_template("t-upper", "upper_2x_a", []), trainer_template("t-lower", "lower_2x_a", [])],
            next_workout_index=1,
        )
        self.garmin_api = fixtures.FakeGarminApi()
        self.garmin_api.renamed = {("BATTLE_ROPE", "BATTLE_ROPE"): "ALTERNATING_WAVE"}
        self.clock = fixtures.FakeClock()
        self.tokens: list[str | None] = []
        self.asked: list[str] = []
        self.answers: list[str] = []
        patcher = mock.patch.object(garminconnect, "Garmin", lambda **_: self.garmin_api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_garmin(self, token: str | None, store: Store) -> lc.CheckGarmin:
        """The script's own `CheckGarmin.open`, then the same fake on a clock that moves only when it waits."""
        self.tokens.append(token)
        lc.CheckGarmin.open(token, store)
        return lc.CheckGarmin(
            self.garmin_api,  # type: ignore[arg-type]
            store,
            sleep=self.clock.sleep,
            clock=self.clock,
        )

    def ask(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0) if self.answers else ""

    def record(self, env: dict[str, str] | None = None, sign_in: Any = lambda: TOKEN) -> tuple[int, str]:
        out = io.StringIO()
        code = lc.record(
            {"HEVY_API_KEY": API_KEY, "HEVY_SESSION": fixtures.HEVY_SESSION_COOKIE} if env is None else env,
            self.folder,
            out,
            ask=self.ask,
            sign_in=sign_in,
            open_garmin=self.open_garmin,
            hevy_session=self.hevy_api,  # type: ignore[arg-type]
            private_session=self.private_api,  # type: ignore[arg-type]
            utcnow=lambda: fixtures.NOW.astimezone(UTC),
        )
        return code, out.getvalue()

    def cleanup(self) -> tuple[int, str]:
        out = io.StringIO()
        code = lc.cleanup(
            self.folder, out, open_garmin=self.open_garmin, utcnow=lambda: fixtures.NOW.astimezone(UTC)
        )
        return code, out.getvalue()

    def names(self) -> list[str]:
        return sorted(w["workoutName"] for w in self.garmin_api.workouts.values())

    def saved(self) -> dict[str, Any]:
        recorded: dict[str, Any] = json.loads(self.store.read(lc.RECORDED) or "{}")
        return recorded


class RecordTest(LiveCheckCase):
    def test_it_makes_the_seven_check_workouts_on_today_and_sends_each_to_the_watch(self) -> None:
        code, out = self.record()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), sorted(lc.NAMES))
        self.assertEqual({e["calendarDate"] for e in self.garmin_api.entries.values()}, {fixtures.TODAY.isoformat()})
        self.assertEqual(len(self.garmin_api.entries), 7)
        self.assertEqual(sorted(self.garmin_api.pushed), sorted(self.garmin_api.workouts))
        created = json.loads(self.store.read(lc.CREATED) or "{}")
        self.assertEqual(sorted(created["workouts"]), sorted(self.garmin_api.workouts))
        self.assertIn("make live-cleanup", out)

    def test_garmin_writes_are_a_second_apart_as_the_app_spaces_them(self) -> None:
        self.record()
        kinds = ("upload_workout", "schedule_workout", "push_workout_to_device")
        self.assertEqual(len([call for call in self.garmin_api.calls if call in kinds]), 21)
        self.assertEqual(self.clock.sleeps, [1.0] * 20)  # O-1b

    def test_no_check_workout_carries_the_apps_description(self) -> None:
        self.assertIsNone(workout.owner(lc.DESCRIPTION))
        self.record()
        for stored in self.garmin_api.workouts.values():
            self.assertEqual(stored["description"], lc.DESCRIPTION)
            self.assertIsNone(workout.owner(stored["description"]))

    def test_it_prints_the_exercise_sent_and_the_one_garmin_stored_for_every_step(self) -> None:
        code, out = self.record()
        rows = lc.checked_rows()
        self.assertGreater(len(rows), 0)
        self.assertEqual({category for category, _ in rows}, set(lc.CHECKED_CATEGORIES))
        steps = self.saved()["garmin"]["steps"]
        self.assertEqual(len(steps), len(rows) + 1)
        self.assertIn("sent BATTLE_ROPE / BATTLE_ROPE, Garmin stored BATTLE_ROPE / ALTERNATING_WAVE", out)
        self.assertIn("sent HYPEREXTENSION / HYPEREXTENSION, Garmin stored HYPEREXTENSION / HYPEREXTENSION", out)
        wanted = f"Step {len(steps)}: sent CORE with a stepName and no exercise, Garmin stored CORE / None"
        self.assertEqual(steps[-1], f"{wanted}, stepName kept")

    def test_the_step_name_step_sends_a_name_and_no_exercise(self) -> None:
        self.record()
        (names,) = [w for w in self.garmin_api.workouts.values() if w["workoutName"] == lc.NAMES_WORKOUT]
        last = list(lc.sets(names))[-1]
        self.assertEqual(last["stepName"], lc.STEP_NAME)
        self.assertNotIn("exerciseName", last)

    def test_set_steps_inside_a_repeat_group_are_read_and_rests_left_out(self) -> None:
        three = workout.Exercise("Check", "CURL", "CURL", (workout.Set(reps=10),) * 3, rest_seconds=60)
        body = workout.build(workout.Workout(workout.ROUTINE, "check", "Check", (three,)), None)
        self.assertEqual(body["workoutSegments"][0]["workoutSteps"][0]["type"], "RepeatGroupDTO")
        self.assertEqual([step["exerciseName"] for step in lc.sets(body)], ["CURL"])

    def test_a_step_name_garmin_drops_is_reported(self) -> None:
        sent = lc.names_body(None)
        stored = json.loads(json.dumps(sent))
        del list(lc.sets(stored))[-1]["stepName"]
        self.assertTrue(lc.compare(sent, stored)[-1].endswith("stepName not kept"))

    def test_it_saves_and_prints_every_shape_and_the_two_trainer_indexes(self) -> None:
        _, out = self.record()
        saved = self.saved()
        self.assertEqual(
            sorted(saved["hevy"]), ["exercise_history", "folders", "routines", "template", "workout_events"]
        )
        self.assertEqual(
            sorted(saved["hevy_trainer"]),
            [
                "exercise_template_units",
                "program",
                "trainer_preferences",
                "user_preferences",
                "user_workouts_paged",
            ],
        )
        self.assertEqual(
            sorted(saved["garmin"]),
            [
                "calendar",
                "not_sent_to_the_watch",
                "schedule_reply",
                "settings",
                "steps",
                "stored_workout",
                "workout_list_item",
            ],
        )
        self.assertEqual(saved["hevy_trainer_order"], {"next_workout_index": 1, "template_index_values": [0, 1]})
        folder = {"created_at": "str", "id": "int", "index": "int", "title": "str", "updated_at": "str"}
        self.assertEqual(saved["hevy"]["folders"], [folder])
        self.assertEqual(saved["hevy_trainer"]["exercise_template_units"], {"<key>": {"unit": "str"}})
        self.assertIn(json.dumps(saved, indent=1, sort_keys=True), out)

    def test_no_value_reaches_the_output_or_the_saved_file(self) -> None:
        _, out = self.record()
        written = "\n".join(p.read_text(encoding="utf-8") for p in self.folder.iterdir() if p.name != garmin.TOKENS)
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, out)
                self.assertNotIn(secret, written)

    def test_it_never_writes_to_hevy_and_keeps_no_hevy_session(self) -> None:
        self.record()
        self.assertEqual([p for p, _ in self.private_api.requests if p == "auth/refresh_token"], [])
        self.assertTrue(all(not hasattr(self.hevy_api, verb) for verb in ("post", "put", "delete")))
        self.assertEqual(
            sorted(p.name for p in self.folder.iterdir()),
            [lc.CREATED, garmin.TOKENS, f"{garmin.TOKENS}.seed", lc.RECORDED],
        )

    def test_the_garmin_token_is_its_own_sign_in_kept_only_in_the_folder(self) -> None:
        self.record()
        self.assertEqual(self.tokens, [TOKEN])
        self.assertEqual(self.store.read(garmin.TOKENS), fixtures.GARMIN_TOKENS)

    def test_without_a_session_it_asks_once_and_skips_hevy_trainer(self) -> None:
        self.hevy_api.routines = []
        self.answers = [API_KEY, ""]
        code, _ = self.record(env={})
        self.assertEqual(code, 0)
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(self.hevy_api.headers[0]["api-key"], API_KEY)
        self.assertEqual(self.private_api.requests, [])
        self.assertEqual(sorted(self.saved()["hevy"]), ["folders", "routines", "workout_events"])
        self.assertNotIn("hevy_trainer", self.saved())

    def test_an_account_with_no_program_still_records_the_rest(self) -> None:
        self.private_api.program = None
        self.record()
        self.assertEqual(
            self.saved()["hevy_trainer_order"], {"next_workout_index": "NoneType", "template_index_values": []}
        )

    def test_an_index_that_is_not_a_whole_number_shows_as_its_type(self) -> None:
        self.assertEqual([lc.index_value(v) for v in (2, True, "1", None)], [2, "bool", "str", "NoneType"])

    def test_a_profile_without_a_usable_zone_puts_them_on_todays_utc_date(self) -> None:
        for zone in (None, "Not/AZone"):
            with self.subTest(zone=zone):
                self.setUp()
                self.garmin_api.zone = zone
                self.assertEqual(self.record()[0], 0)
                days = {e["calendarDate"] for e in self.garmin_api.entries.values()}
                self.assertEqual(days, {fixtures.NOW.astimezone(UTC).date().isoformat()})

    def test_a_watch_that_takes_none_is_counted_and_the_run_goes_on(self) -> None:
        self.garmin_api.fail("push_workout_to_device", *[fixtures.garmin_error(400)] * 7)
        code, _ = self.record()
        self.assertEqual(code, 0)
        self.assertEqual(self.saved()["garmin"]["not_sent_to_the_watch"], 7)

    def test_an_earlier_run_not_cleaned_up_stops_it_before_any_call(self) -> None:
        self.store.write(lc.CREATED, json.dumps({"workouts": [1]}))
        code, out = self.record()
        self.assertEqual(code, 1)
        self.assertIn("run `make live-cleanup` first", out)
        self.assertEqual((self.hevy_api.requests, self.garmin_api.calls), ([], []))

    def test_hevy_failing_stops_it_before_the_garmin_sign_in(self) -> None:
        signed_in: list[bool] = []

        def sign_in() -> str:
            signed_in.append(True)
            return TOKEN

        self.hevy_api.fail(503)
        code, out = self.record(sign_in=sign_in)
        self.assertEqual(code, 1)
        self.assertIn("Reading Hevy failed (Unavailable). Nothing was made in Garmin.", out)
        self.assertEqual(signed_in, [])

    def test_a_cookie_that_is_not_one_says_so(self) -> None:
        code, out = self.record(env={"HEVY_API_KEY": API_KEY, "HEVY_SESSION": "not-it"})
        self.assertEqual(code, 1)
        self.assertIn("HEVY_SESSION is not the auth2.0-token cookie", out)
        self.assertNotIn("not-it", out)

    def test_a_refused_sign_in_makes_nothing(self) -> None:
        def refused() -> str:
            raise garminconnect.GarminConnectTooManyRequestsError("Too many login attempts.")

        code, out = self.record(sign_in=refused)
        self.assertEqual(code, 1)
        self.assertIn("The Garmin sign-in failed (GarminConnectTooManyRequestsError)", out)
        self.assertEqual(self.garmin_api.workouts, {})
        self.assertIn("hevy", self.saved())

    def test_a_garmin_failure_partway_names_what_was_made_and_leaves_its_ids(self) -> None:
        self.garmin_api.fail("schedule_workout", fixtures.garmin_error(500))
        code, out = self.record()
        self.assertEqual(code, 1)
        self.assertIn("Garmin failed partway (Unavailable). 7 of 7 check workouts were made", out)
        self.assertEqual(len(json.loads(self.store.read(lc.CREATED) or "{}")["workouts"]), 7)


class CleanupTest(LiveCheckCase):
    def test_it_removes_only_its_workouts_and_entries_then_the_token(self) -> None:
        self.garmin_api.workouts[1] = {"workoutId": 1, "workoutName": "HGS check 1", "description": "someone else's"}
        self.garmin_api.workouts[2] = {"workoutId": 2, "workoutName": "Hevy: Push", "description": workout.FIRST_LINE}
        self.garmin_api.schedule_workout(2, fixtures.TODAY.isoformat())
        self.record()
        code, out = self.cleanup()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), ["HGS check 1", "Hevy: Push"])
        self.assertEqual([e["workout"]["workoutId"] for e in self.garmin_api.entries.values()], [2])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [lc.RECORDED])
        self.assertIn("Removed 7 calendar entries and 7 check workouts", out)

    def test_a_second_run_has_nothing_to_do(self) -> None:
        self.record()
        self.cleanup()
        self.assertEqual(self.cleanup(), (0, "Nothing to clean up.\n"))

    def test_with_no_id_file_it_goes_by_the_seven_names_alone(self) -> None:
        self.garmin_api.fail("upload_workout", fixtures.garmin_error(500))
        self.record()
        self.store.remove(lc.CREATED)
        self.garmin_api.workouts[1] = {"workoutId": 1, "workoutName": "HGS check 6"}
        self.garmin_api.workouts[2] = {"workoutId": 2, "workoutName": "HGS check 7"}
        code, out = self.cleanup()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), ["HGS check 7"])
        self.assertIn("Removed 0 calendar entries and 1 check workouts", out)

    def test_an_id_file_without_the_token_says_to_delete_by_hand(self) -> None:
        self.store.write(lc.CREATED, json.dumps({"workouts": [1]}))
        code, out = self.cleanup()
        self.assertEqual(code, 1)
        self.assertIn("Delete the workouts named `HGS check ...` in Garmin Connect by hand", out)

    def test_a_garmin_failure_keeps_the_token_and_the_ids_for_another_try(self) -> None:
        self.record()
        self.garmin_api.fail("get_workouts", fixtures.garmin_error(500))
        code, out = self.cleanup()
        self.assertEqual(code, 1)
        self.assertIn("Cleanup failed (Unavailable). Run `make live-cleanup` again.", out)
        self.assertIsNotNone(self.store.read(lc.CREATED))
        self.assertIsNotNone(self.store.read(garmin.TOKENS))


class ShapeTest(unittest.TestCase):
    def test_keys_that_could_be_values_are_hidden_and_field_names_kept(self) -> None:
        reply = {
            "workoutId": 1,
            "userData": {"timeZone": "America/Los_Angeles"},
            "2026-01-15": [{"exercise_template_id": "T-BENCH"}],
            "D04AC939": "kg",
            "someone@example.com": None,
        }
        self.assertEqual(
            lc.shape(reply),
            {"workoutId": "int", "userData": {"timeZone": "str"}, "<key>": "NoneType"},
        )


class MainTest(unittest.TestCase):
    def test_each_command_runs_its_function_on_the_folder_in_the_repo(self) -> None:
        for command in ("record", "cleanup"):
            with self.subTest(command=command), mock.patch.object(lc, command, return_value=0) as run:
                self.assertEqual(lc.main([command], env={}, out=io.StringIO()), 0)
                self.assertEqual(run.call_args.args[-2], lc.FOLDER)
        self.assertEqual(lc.FOLDER, Path(lc.__file__).resolve().parents[1] / "live-check")


if __name__ == "__main__":
    unittest.main()
