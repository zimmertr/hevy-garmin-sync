"""The Garmin client: where the token comes from, how failures are told apart, and the pause between writes."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import garminconnect
import requests

from hevy_garmin_sync import errors, garmin
from hevy_garmin_sync.store import Store
from tests import fixtures

ENV_TOKEN = garmin.encode_token(fixtures.GARMIN_TOKENS)


class GarminCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name))
        self.api = fixtures.FakeGarminApi()
        self.clock = fixtures.FakeClock()
        # The fake stands in for the library's class; the wrapper only uses what the fake has.
        self.garmin = garmin.Garmin(self.api, self.store, sleep=self.clock.sleep, clock=self.clock)  # type: ignore[arg-type]


class TokenTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name))
        patcher = mock.patch.object(garminconnect, "Garmin", fixtures.FakeGarminApi)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open(self, env_token: str | None) -> fixtures.FakeGarminApi:
        api = garmin.Garmin.open(env_token, self.store)._api
        assert isinstance(api, fixtures.FakeGarminApi)
        return api

    def test_the_login_value_round_trips(self) -> None:
        self.assertEqual(garmin.decode_token(ENV_TOKEN), fixtures.GARMIN_TOKENS)
        self.assertEqual(garmin.decode_token(f"  {ENV_TOKEN}\n"), fixtures.GARMIN_TOKENS)
        self.assertNotIn(" ", ENV_TOKEN)

    def test_the_first_start_seeds_the_store_from_the_environment(self) -> None:
        api = self.open(ENV_TOKEN)
        self.assertEqual(self.store.read(garmin.TOKENS), fixtures.GARMIN_TOKENS)
        self.assertEqual(api.client.loaded_from, str(self.store.path(garmin.TOKENS)))
        self.assertEqual(api.client.dumps(), fixtures.GARMIN_TOKENS)

    def test_the_library_is_told_not_to_retry(self) -> None:
        self.assertEqual(self.open(ENV_TOKEN).init_kwargs, {"retry_attempts": 0})

    def test_the_stored_copy_wins_while_the_environment_value_is_unchanged(self) -> None:
        self.open(ENV_TOKEN)
        self.store.write(garmin.TOKENS, json.dumps({"di_token": "rotated"}))
        self.assertEqual(json.loads(self.open(ENV_TOKEN).client.dumps()), {"di_token": "rotated"})

    def test_a_new_environment_value_replaces_the_stored_copy(self) -> None:
        self.open(ENV_TOKEN)
        again = garmin.encode_token(json.dumps({"di_token": "from a second login"}))
        self.assertEqual(json.loads(self.open(again).client.dumps()), {"di_token": "from a second login"})
        self.assertTrue(self.store.seeded_by(garmin.TOKENS, again))

    def test_the_stored_copy_alone_is_enough(self) -> None:
        self.open(ENV_TOKEN)
        self.assertEqual(self.open(None).client.dumps(), fixtures.GARMIN_TOKENS)
        self.assertEqual(self.open("").client.dumps(), fixtures.GARMIN_TOKENS)

    def test_a_lost_token_file_is_seeded_again(self) -> None:
        self.open(ENV_TOKEN)
        self.store.remove(garmin.TOKENS)
        self.assertEqual(self.open(ENV_TOKEN).client.dumps(), fixtures.GARMIN_TOKENS)

    def test_no_token_anywhere_is_a_configuration_error_that_names_the_fix(self) -> None:
        with self.assertRaisesRegex(errors.ConfigError, "GARMIN_TOKEN is not set.*run `login` again"):
            self.open(None)

    def test_a_value_login_did_not_print_is_a_configuration_error(self) -> None:
        not_json = base64.b64encode(b"not json").decode()
        no_token = base64.b64encode(b'{"di_refresh_token": "x"}').decode()
        a_list = base64.b64encode(b"[1]").decode()
        for value in ("not base64 at all!", not_json, no_token, a_list):
            with self.subTest(value=value), self.assertRaisesRegex(errors.ConfigError, "GARMIN_TOKEN is not a value"):
                self.open(value)
        self.assertIsNone(self.store.read(garmin.TOKENS))

    def test_an_unreadable_stored_token_is_a_configuration_error(self) -> None:
        self.store.write(garmin.TOKENS, "{}")
        with self.assertRaisesRegex(errors.ConfigError, "can't be read.*run `login` again"):
            self.open(None)


class RotationTest(GarminCase):
    def test_a_token_garmin_rotated_during_a_call_is_saved(self) -> None:
        self.api.rotate_token_on("get_workouts")
        self.garmin.workouts()
        self.assertEqual(self.store.read(garmin.TOKENS), self.api.client.dumps())
        self.assertIn("refresh-2", self.store.read(garmin.TOKENS) or "")

    def test_it_is_saved_even_when_the_call_then_fails(self) -> None:
        self.api.rotate_token_on("upload_workout")
        self.api.fail("upload_workout", fixtures.garmin_error(500))
        with self.assertRaises(errors.Unavailable):
            self.garmin.create({})
        self.assertIn("refresh-2", self.store.read(garmin.TOKENS) or "")

    def test_an_unchanged_token_is_not_written(self) -> None:
        self.garmin.workouts()
        self.assertIsNone(self.store.read(garmin.TOKENS))

    def test_a_failed_save_is_logged_with_the_fix_and_tried_again(self) -> None:
        self.api.rotate_token_on("get_workouts")
        with (
            mock.patch.object(self.store, "write", side_effect=OSError("read-only file system")),
            self.assertLogs("hevy_garmin_sync.garmin", "ERROR") as logs,
        ):
            self.garmin.workouts()
        self.assertIn("run `login` again", logs.output[0])
        self.assertNotIn("refresh-2", logs.output[0])
        self.garmin.workouts()
        self.assertIn("refresh-2", self.store.read(garmin.TOKENS) or "")


class ErrorTest(GarminCase):
    def test_each_failure_becomes_one_of_the_apps_own(self) -> None:
        cases: list[tuple[BaseException, type[errors.ServiceError]]] = [
            (garminconnect.GarminConnectAuthenticationError("Authentication failed"), errors.Rejected),
            (garminconnect.GarminConnectTooManyRequestsError("Rate limit exceeded"), errors.RateLimited),
            (fixtures.garmin_error(401), errors.Rejected),
            (fixtures.garmin_error(403), errors.Rejected),
            (fixtures.garmin_error(429), errors.RateLimited),
            (fixtures.garmin_error(404), errors.NotFound),
            (fixtures.garmin_error(400, "Invalid workout"), errors.Refused),
            (fixtures.garmin_error(500), errors.Unavailable),
            (fixtures.garmin_error(503), errors.Unavailable),
            (garminconnect.GarminConnectConnectionError("Connection error: timed out"), errors.Unavailable),
            (requests.ConnectionError("no route"), errors.Unavailable),
            (requests.Timeout("read timed out"), errors.Unavailable),
            (KeyError("userDeviceId"), errors.Refused),
        ]
        for raised, expected in cases:
            with self.subTest(raised=raised):
                self.api.fail("upload_workout", raised)
                with self.assertRaises(expected) as caught:
                    self.garmin.create({})
                self.assertIs(type(caught.exception), expected)

    def test_garmins_reason_for_refusing_a_workout_is_kept(self) -> None:
        self.api.fail("upload_workout", fixtures.garmin_error(400, "Invalid workout"))
        with self.assertRaisesRegex(errors.Refused, "API Error 400 - Invalid workout"):
            self.garmin.create({})

    def test_deleting_what_is_already_gone_is_not_an_error(self) -> None:
        self.garmin.delete(42)
        self.garmin.unschedule(42)
        self.assertEqual(self.api.calls, ["delete_workout", "unschedule_workout"])

    def test_updating_what_is_gone_is(self) -> None:
        with self.assertRaises(errors.NotFound):
            self.garmin.update(42, {})


class CallsTest(GarminCase):
    def test_the_measurement_system_comes_from_the_user_settings(self) -> None:
        self.assertEqual(self.garmin.measurement_system(), "statute_us")
        self.api.measurement_system = None
        self.assertIsNone(self.garmin.measurement_system())

    def test_a_rejected_token_shows_on_the_first_call(self) -> None:
        self.api.fail("get_user_profile", garminconnect.GarminConnectAuthenticationError("Authentication failed"))
        with self.assertRaises(errors.Rejected):
            self.garmin.measurement_system()

    def test_the_time_zone_is_the_profiles(self) -> None:
        self.assertEqual(self.garmin.time_zone(), "America/Los_Angeles")
        self.assertEqual(self.api.calls, ["connectapi", "get_user_timezone"])

    def test_no_time_zone_is_none_whether_garmin_has_none_or_fails(self) -> None:
        self.api.zone = None
        self.assertIsNone(self.garmin.time_zone())
        self.api.fail("connectapi", fixtures.garmin_error(500))
        self.assertIsNone(self.garmin.time_zone())

    def test_the_workout_list_is_read_page_by_page_until_a_short_page(self) -> None:
        for n in range(205):
            self.api.workouts[n] = {"workoutId": n, "workoutName": f"w{n}", "description": None}
        listed = self.garmin.workouts()
        self.assertEqual([w["workoutId"] for w in listed], list(range(205)))
        self.assertEqual(self.api.calls, ["get_workouts"] * 3)

    def test_an_exactly_full_page_is_followed_by_one_more_call(self) -> None:
        for n in range(100):
            self.api.workouts[n] = {"workoutId": n}
        self.assertEqual(len(self.garmin.workouts()), 100)
        self.assertEqual(self.api.calls, ["get_workouts"] * 2)

    def test_a_workout_is_created_updated_sent_and_deleted(self) -> None:
        workout_id = self.garmin.create({"workoutName": "Hevy: Core"})
        self.garmin.update(workout_id, {"workoutName": "Hevy: Abs"})
        self.assertEqual(self.api.workouts[workout_id]["workoutName"], "Hevy: Abs")
        self.garmin.send_to_device(workout_id)
        self.assertEqual(self.api.pushed, [workout_id])
        self.garmin.delete(workout_id)
        self.assertEqual(self.api.workouts, {})

    def test_the_calendar_is_read_and_written_by_day(self) -> None:
        workout_id = self.garmin.create({})
        self.garmin.schedule(workout_id, fixtures.TODAY)
        (entry,) = self.garmin.scheduled(fixtures.TODAY, fixtures.TODAY)
        self.assertEqual(entry["calendarDate"], fixtures.TODAY.isoformat())
        self.assertEqual(entry["workout"]["workoutId"], workout_id)
        self.garmin.unschedule(entry["workoutScheduleId"])
        self.assertEqual(self.garmin.scheduled(fixtures.TODAY, fixtures.TODAY), [])


class PacingTest(GarminCase):
    def test_writes_are_at_least_a_second_apart(self) -> None:
        workout_id = self.garmin.create({})
        self.garmin.update(workout_id, {})
        self.garmin.send_to_device(workout_id)
        self.assertEqual(self.clock.sleeps, [1.0, 1.0])

    def test_only_the_missing_part_of_the_second_is_waited(self) -> None:
        self.garmin.create({})
        self.clock.now += 0.75
        self.garmin.create({})
        self.assertEqual(self.clock.sleeps, [0.25])
        self.clock.now += 5
        self.garmin.create({})
        self.assertEqual(self.clock.sleeps, [0.25])

    def test_reads_never_wait(self) -> None:
        self.garmin.create({})
        self.garmin.workouts()
        self.garmin.scheduled(fixtures.TODAY, fixtures.TODAY)
        self.assertEqual(self.clock.sleeps, [])

    def test_a_failed_write_still_counts_as_a_write(self) -> None:
        self.api.fail("upload_workout", fixtures.garmin_error(500))
        with self.assertRaises(errors.Unavailable):
            self.garmin.create({})
        self.garmin.create({})
        self.assertEqual(self.clock.sleeps, [1.0])


if __name__ == "__main__":
    unittest.main()
