"""Hevy's private API: the session and its refresh, and the reads Hevy Trainer needs (spec A-3, A-4)."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import requests

from hevy_garmin_sync import errors, hevy_private
from hevy_garmin_sync.hevy_private import SESSION, HevyPrivate
from hevy_garmin_sync.store import Store
from tests import fixtures

NOW = fixtures.NOW.astimezone(UTC)


class PrivateCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name))
        self.api = fixtures.FakeHevyPrivateApi()

    def client(self, **tokens: str | None) -> HevyPrivate:
        return HevyPrivate(
            fixtures.HEVY_SESSION_TOKENS | tokens,
            self.store,
            self.api,  # type: ignore[arg-type]
            utcnow=lambda: NOW,
        )

    def stored(self) -> dict[str, str]:
        found: dict[str, str] = json.loads(self.store.read(SESSION) or "{}")
        return found


class TimeTest(unittest.TestCase):
    def test_a_time_is_unix_seconds_or_iso_8601(self) -> None:
        moment = datetime(2026, 11, 3, 23, 13, 14, tzinfo=UTC)
        self.assertEqual(hevy_private.parse_time(1793747594), moment)
        self.assertEqual(hevy_private.parse_time(1793747594.0), moment)
        self.assertEqual(hevy_private.parse_time("2026-11-03T23:13:14.000Z"), moment)
        self.assertEqual(hevy_private.parse_time("2026-11-03T15:13:14-08:00"), moment)

    def test_a_time_with_no_zone_is_utc(self) -> None:
        self.assertEqual(hevy_private.parse_time("2026-11-03T23:13:14"), datetime(2026, 11, 3, 23, 13, 14, tzinfo=UTC))

    def test_anything_else_is_no_time(self) -> None:
        nothing: list[object] = [None, True, "next Tuesday", "", {}]
        for junk in nothing:
            with self.subTest(junk=junk):
                self.assertIsNone(hevy_private.parse_time(junk))


class CookieTest(unittest.TestCase):
    def test_the_cookie_is_url_encoded_json_holding_the_tokens(self) -> None:
        self.assertEqual(hevy_private.parse_cookie(f"  {fixtures.HEVY_SESSION_COOKIE}\n"), fixtures.HEVY_SESSION_TOKENS)

    def test_plain_json_is_taken_too_and_extra_fields_are_dropped(self) -> None:
        tokens = hevy_private.parse_cookie(json.dumps(fixtures.HEVY_SESSION_TOKENS | {"user_id": "someone"}))
        self.assertEqual(tokens, fixtures.HEVY_SESSION_TOKENS)

    def test_anything_else_names_the_variable_and_the_fix(self) -> None:
        for value in ("just-an-access-token", '"a string"', '{"access_token": "only half"}', "[]"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(errors.ConfigError, "^HEVY_SESSION is not .* copy the auth2.0-token cookie"),
            ):
                hevy_private.parse_cookie(value)

    def test_the_message_never_holds_the_value(self) -> None:
        with self.assertRaises(errors.ConfigError) as caught:
            hevy_private.parse_cookie("made-up-secret")
        self.assertNotIn("made-up-secret", str(caught.exception))


class OpenTest(PrivateCase):
    def open(self, cookie: str = fixtures.HEVY_SESSION_COOKIE) -> HevyPrivate:
        return HevyPrivate.open(cookie, self.store, self.api)  # type: ignore[arg-type]

    def test_the_first_start_stores_the_session_from_the_variable_without_a_call(self) -> None:
        self.open()
        self.assertEqual(self.stored(), fixtures.HEVY_SESSION_TOKENS)
        self.assertTrue(self.store.seeded_by(SESSION, fixtures.HEVY_SESSION_COOKIE))
        self.assertEqual(self.api.requests, [])

    def test_a_later_start_uses_the_stored_session_not_the_variable(self) -> None:
        self.open()
        rotated = fixtures.HEVY_SESSION_TOKENS | {"access_token": "hevy-access-2", "refresh_token": "hevy-refresh-2"}
        self.store.write(SESSION, json.dumps(rotated))
        self.api.access = "hevy-access-2"
        self.open().user_preferences()
        self.assertEqual(self.api.headers[0]["Authorization"], "Bearer hevy-access-2")

    def test_a_new_value_in_the_variable_replaces_the_stored_session(self) -> None:
        self.open()
        again = json.dumps(fixtures.HEVY_SESSION_TOKENS | {"access_token": "hevy-access-9"})
        self.open(again)
        self.assertEqual(self.stored()["access_token"], "hevy-access-9")
        self.assertTrue(self.store.seeded_by(SESSION, again))

    def test_a_value_that_is_not_the_cookie_stores_nothing(self) -> None:
        with self.assertRaises(errors.ConfigError):
            self.open("not-the-cookie")
        self.assertIsNone(self.store.read(SESSION))

    def test_the_session_file_is_readable_only_by_the_app(self) -> None:
        self.open()
        self.assertEqual(self.store.path(SESSION).stat().st_mode & 0o777, 0o600)


class RequestTest(PrivateCase):
    def test_every_call_carries_the_web_key_the_session_a_user_agent_and_a_timeout(self) -> None:
        client = self.client()
        client.user_preferences()
        headers = self.api.headers[0]
        self.assertEqual(headers["x-api-key"], "shelobs_hevy_web")
        self.assertEqual(headers["Authorization"], "Bearer hevy-access-1")
        self.assertIn("hevy-garmin-sync", headers["User-Agent"])
        self.assertGreater(float(headers["x-client-time"]), 0)
        self.assertEqual(self.api.timeouts, [30])
        self.assertEqual(client.calls, 1)

    def test_failures_become_the_apps_own_errors(self) -> None:
        cases: list[tuple[BaseException | int | str, type[errors.ServiceError]]] = [
            (429, errors.RateLimited),
            (400, errors.Refused),
            (503, errors.Unavailable),
            (requests.Timeout("read timed out"), errors.Unavailable),
            ("<html>a proxy's error page</html>", errors.Unavailable),
        ]
        for failure, expected in cases:
            with self.subTest(failure=failure):
                self.api.fail(failure)
                with self.assertRaises(expected):
                    self.client().user_preferences()


class RefreshTest(PrivateCase):
    def test_a_session_that_has_not_expired_is_used_as_it_is(self) -> None:
        self.client().user_preferences()
        self.assertEqual(self.api.paths(), ["v2/user_preferences"])

    def test_an_expired_session_is_refreshed_first_and_the_new_pair_saved(self) -> None:
        client = self.client(expires_at="2026-01-15T00:00:00.000Z")
        client.user_preferences()
        self.assertEqual(self.api.paths(), ["auth/refresh_token", "v2/user_preferences"])
        self.assertEqual(self.api.requests[0][1], {"refresh_token": "hevy-refresh-1"})
        self.assertEqual(self.api.headers[1]["Authorization"], "Bearer hevy-access-2")
        self.assertEqual(self.stored()["refresh_token"], "hevy-refresh-2")
        self.assertEqual(client.calls, 2)

    def test_the_refresh_carries_the_old_access_token_which_hevy_insists_on(self) -> None:
        self.client(expires_at="2026-01-15T00:00:00.000Z").user_preferences()
        self.assertEqual(self.api.headers[0]["Authorization"], "Bearer hevy-access-1")

    def test_a_session_with_no_expiry_or_an_unreadable_one_counts_as_expired(self) -> None:
        for expires_at in (None, "soon"):
            with self.subTest(expires_at=expires_at):
                self.setUp()
                self.client(expires_at=expires_at).user_preferences()
                self.assertEqual(self.api.paths()[0], "auth/refresh_token")

    def test_the_new_pair_is_on_disk_before_the_next_call_is_made(self) -> None:
        """Hevy has already killed the old refresh token, so a crash here must not lose the new one."""
        self.api.fail(None, requests.ConnectionError("down"))
        with self.assertRaises(errors.Unavailable):
            self.client(expires_at="2026-01-15T00:00:00.000Z").user_preferences()
        self.assertEqual(self.stored()["refresh_token"], "hevy-refresh-2")

    def test_a_401_refreshes_once_and_asks_again(self) -> None:
        self.api.access = "hevy-access-other"  # Hevy ended the access token early
        self.assertEqual(self.client().user_preferences()["username"], "someone")
        self.assertEqual(self.api.paths(), ["v2/user_preferences", "auth/refresh_token", "v2/user_preferences"])

    def test_a_401_after_the_refresh_is_a_rejected_session(self) -> None:
        self.api.fail(401, None, 401)
        with self.assertRaises(errors.Rejected):
            self.client().user_preferences()
        self.assertEqual(len(self.api.requests), 3)

    def test_a_refresh_hevy_will_not_do_is_a_rejected_session(self) -> None:
        for answer in (400, 401, 404):
            with self.subTest(answer=answer):
                self.setUp()
                self.api.fail(answer)
                with self.assertRaisesRegex(errors.Rejected, "Hevy would not refresh the session|HTTP 401"):
                    self.client(expires_at=None).user_preferences()
                self.assertEqual(self.stored(), {})

    def test_a_refresh_token_another_client_already_used_is_a_rejected_session(self) -> None:
        self.api.refresh = "hevy-refresh-taken"
        with self.assertRaises(errors.Rejected):
            self.client(expires_at=None).user_preferences()

    def test_an_outage_during_the_refresh_is_an_outage_and_the_session_is_kept(self) -> None:
        self.api.fail(503)
        client = self.client(expires_at=None)
        with self.assertRaises(errors.Unavailable):
            client.user_preferences()
        client.user_preferences()
        self.assertEqual(self.stored()["refresh_token"], "hevy-refresh-2")

    def test_a_refresh_reply_with_no_access_token_is_a_rejected_session(self) -> None:
        replies: list[Any] = [{"error": "made up"}, []]
        for reply in replies:
            with self.subTest(reply=reply):
                self.setUp()
                self.api.refresh_reply = reply
                with self.assertRaisesRegex(errors.Rejected, "no access token"):
                    self.client(expires_at=None).user_preferences()

    def test_a_refresh_reply_with_no_new_refresh_token_keeps_the_old_one(self) -> None:
        self.api.refresh_reply = {"access_token": "hevy-access-2", "expires_at": "2999-01-01T00:00:00.000Z"}
        self.client(expires_at=None).user_preferences()
        self.assertEqual(self.stored()["refresh_token"], "hevy-refresh-1")


class ReadTest(PrivateCase):
    def test_the_two_sets_of_preferences_are_objects(self) -> None:
        client = self.client()
        self.assertEqual(client.user_preferences()["first_weekday"], "monday")
        self.assertIn("availableWeights", client.trainer_preferences())
        self.assertEqual(self.api.paths(), ["v2/user_preferences", "hevy_trainer/user_preferences"])

    def test_a_preferences_reply_in_another_shape_reads_as_empty(self) -> None:
        self.api.user = ["not", "an", "object"]
        self.api.trainer = None
        self.assertEqual(self.client().user_preferences(), {})
        self.assertEqual(self.client().trainer_preferences(), {})

    def test_the_unit_overrides_come_back_as_hevy_sent_them(self) -> None:
        self.api.units = [{"exercise_template_id": "T-BENCH", "weight_unit": "kg"}]
        self.assertEqual(self.client().unit_overrides(), self.api.units)

    def test_the_program_is_asked_for_whole(self) -> None:
        self.api.program = fixtures.trainer_program([])
        self.assertEqual((self.client().program() or {})["id"], "program-1")
        path, params = self.api.requests[0]
        self.assertEqual(path, "hevy_trainer/v3/program")
        self.assertEqual(set(params.values()), {"1970-01-01T00:00:00.000Z"})

    def test_an_account_with_no_program_is_none_not_an_error(self) -> None:
        self.assertIsNone(self.client().program())
        self.api.fail(404)
        self.assertIsNone(self.client().program())

    def test_a_program_reply_that_is_not_an_object_is_no_program(self) -> None:
        with mock.patch.object(self.api, "get", return_value=fixtures.FakeResponse(200, ["odd"])):
            self.assertIsNone(self.client().program())

    def test_a_failing_program_read_raises(self) -> None:
        self.api.fail(503)
        with self.assertRaises(errors.Unavailable):
            self.client().program()


class WorkoutsTest(PrivateCase):
    def setUp(self) -> None:
        super().setUp()
        self.since = fixtures.PROGRAM_START
        # Seven workouts a day apart, the oldest two from before the program.
        self.api.workouts = [
            fixtures.logged_workout("t-upper", self.since + timedelta(days=day), {}) for day in range(-2, 5)
        ]

    def workouts(self) -> list[int]:
        found = self.client().workouts_since("someone", self.since)
        return [(hevy_private.parse_time(w["start_time"]) - self.since).days for w in found]  # type: ignore[operator]

    def test_workouts_are_read_three_at_a_time_newest_first_until_one_is_too_old(self) -> None:
        self.assertEqual(self.workouts(), [4, 3, 2, 1, 0])
        self.assertEqual(
            [params for _, params in self.api.requests],
            [{"username": "someone", "limit": 3, "offset": offset} for offset in (0, 3)],
        )

    def test_a_short_page_is_the_last(self) -> None:
        self.api.workouts = self.api.workouts[2:6]
        self.assertEqual(self.workouts(), [3, 2, 1, 0])
        self.assertEqual(len(self.api.requests), 2)

    def test_an_empty_page_is_the_last(self) -> None:
        self.api.workouts = self.api.workouts[2:5]
        self.assertEqual(self.workouts(), [2, 1, 0])
        self.assertEqual(len(self.api.requests), 2)

    def test_no_workouts_at_all_is_one_call(self) -> None:
        self.api.workouts = []
        self.assertEqual(self.workouts(), [])
        self.assertEqual(len(self.api.requests), 1)

    def test_a_reply_in_another_shape_reads_as_no_workouts(self) -> None:
        with mock.patch.object(self.api, "get", return_value=fixtures.FakeResponse(200, ["odd"])):
            self.assertEqual(self.client().workouts_since("someone", self.since), [])

    def test_a_workout_with_no_start_time_is_kept_and_does_not_end_the_reading(self) -> None:
        self.api.workouts = [{"id": "no-start"}] * 3 + self.api.workouts[:1]
        found = self.client().workouts_since("someone", self.since)
        self.assertEqual([w["id"] for w in found], ["no-start"] * 3)
        self.assertEqual(len(self.api.requests), 2)

    def test_the_reading_stops_at_a_fixed_number_of_pages(self) -> None:
        with mock.patch.object(hevy_private, "_MAX_WORKOUT_PAGES", 1):
            self.assertEqual(self.workouts(), [4, 3, 2])

    def test_a_page_that_fails_fails_the_whole_read(self) -> None:
        self.api.fail(None, 503)
        with self.assertRaises(errors.Unavailable):
            self.workouts()


if __name__ == "__main__":
    unittest.main()
