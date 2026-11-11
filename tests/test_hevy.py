"""The Hevy public client: whole lists or an error, one error vocabulary, a timeout on every call."""

import unittest
from datetime import UTC, datetime, timedelta

import requests

from hevy_garmin_sync import errors, hevy
from tests import fixtures


class HevyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = fixtures.FakeHevyApi()
        self.hevy = hevy.Hevy("made-up-key", self.api)  # type: ignore[arg-type]

    def test_a_list_is_read_page_by_page_to_the_end(self) -> None:
        self.api.routines = [fixtures.hevy_routine(f"r{n}", f"Routine {n}") for n in range(25)]
        self.assertEqual([r["id"] for r in self.hevy.routines()], [f"r{n}" for n in range(25)])
        self.assertEqual(self.api.requests, [("/routines", {"page": n, "pageSize": 10}) for n in (1, 2, 3)])
        self.assertEqual(self.hevy.calls, 3)

    def test_an_empty_list_is_one_call(self) -> None:
        self.assertEqual(self.hevy.folders(), [])
        self.assertEqual(self.api.requests, [("/routine_folders", {"page": 1, "pageSize": 10})])

    def test_a_page_that_fails_fails_the_whole_list(self) -> None:
        self.api.routines = [fixtures.hevy_routine(f"r{n}", f"Routine {n}") for n in range(25)]
        self.api.fail(None, 500)
        with self.assertRaises(errors.Unavailable):
            self.hevy.routines()
        self.assertEqual(len(self.api.requests), 2)

    def test_every_call_carries_the_key_a_user_agent_and_a_timeout(self) -> None:
        self.hevy.folders()
        self.assertEqual(self.api.headers[0]["api-key"], "made-up-key")
        self.assertIn("hevy-garmin-sync", self.api.headers[0]["User-Agent"])
        self.assertEqual(self.api.timeouts, [30])

    def test_each_failure_becomes_one_of_the_apps_own(self) -> None:
        cases: list[tuple[BaseException | int | str, type[errors.ServiceError]]] = [
            (401, errors.Rejected),
            (403, errors.Rejected),
            (429, errors.RateLimited),
            (404, errors.NotFound),
            (400, errors.Refused),
            (500, errors.Unavailable),
            (503, errors.Unavailable),
            (requests.ConnectionError("no route"), errors.Unavailable),
            (requests.Timeout("read timed out"), errors.Unavailable),
            ("<html>a proxy's error page</html>", errors.Unavailable),
        ]
        for failure, expected in cases:
            with self.subTest(failure=failure):
                self.api.fail(failure)
                with self.assertRaises(expected) as caught:
                    self.hevy.folders()
                self.assertIs(type(caught.exception), expected)

    def test_a_rate_limit_carries_the_wait_hevy_asked_for(self) -> None:
        self.api.fail(fixtures.rate_limited("120"))
        with self.assertRaises(errors.RateLimited) as caught:
            self.hevy.folders()
        self.assertEqual(caught.exception.retry_after, 120)

    def test_a_rate_limit_with_no_wait_or_one_that_cant_be_read_carries_none(self) -> None:
        for failure in (429, fixtures.rate_limited("in a while")):
            with self.subTest(failure=failure):
                self.api.fail(failure)
                with self.assertRaises(errors.RateLimited) as caught:
                    self.hevy.folders()
                self.assertIsNone(caught.exception.retry_after)

    def test_a_network_error_never_puts_the_url_in_the_message(self) -> None:
        self.api.fail(requests.ConnectionError("https://api.hevyapp.com/v1/routines?secret=1"))
        with self.assertRaises(errors.Unavailable) as caught:
            self.hevy.folders()
        self.assertEqual(str(caught.exception), "ConnectionError")

    def test_templates_are_read_once_as_a_whole_list(self) -> None:
        self.assertEqual((self.hevy.template("T-BENCH") or {})["title"], "Bench Press (Barbell)")
        self.assertEqual((self.hevy.template("T-PLANK") or {})["type"], "duration")
        self.assertEqual(self.api.requests, [("/exercise_templates", {"page": 1, "pageSize": 100})])

    def test_a_template_made_later_is_read_by_itself_once(self) -> None:
        self.hevy.template("T-BENCH")
        self.api.templates.append(fixtures.hevy_template("T-NEW", "My Curl", is_custom=True))
        self.assertEqual((self.hevy.template("T-NEW") or {})["title"], "My Curl")
        self.hevy.template("T-NEW")
        self.assertEqual([path for path, _ in self.api.requests], ["/exercise_templates", "/exercise_templates/T-NEW"])

    def test_a_template_hevy_does_not_have_is_none_and_is_not_asked_for_twice(self) -> None:
        self.assertIsNone(self.hevy.template("T-GONE"))
        self.assertIsNone(self.hevy.template("T-GONE"))
        self.assertEqual(len(self.api.requests), 2)

    def test_workout_events_are_asked_for_since_an_instant_in_utc(self) -> None:
        since = datetime(2026, 1, 15, 17, 40, tzinfo=fixtures.ZONE)
        self.api.events = [{"type": "deleted", "id": "w1"}]
        self.assertEqual(self.hevy.workout_events(since), [{"type": "deleted", "id": "w1"}])
        self.assertEqual(self.api.requests[0][1]["since"], since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertTrue(self.api.requests[0][1]["since"].endswith("Z"))

    def test_exercise_history_is_one_call_between_two_instants(self) -> None:
        end = fixtures.NOW
        start = end - timedelta(days=365)
        self.api.history["T-BENCH"] = [{"weight_kg": 60, "reps": 8, "set_type": "normal"}]
        self.assertEqual(len(self.hevy.exercise_history("T-BENCH", start, end)), 1)
        self.assertEqual(self.hevy.exercise_history("T-OTHER", start, end), [])
        path, params = self.api.requests[0]
        self.assertEqual(path, "/exercise_history/T-BENCH")
        self.assertEqual(sorted(params), ["end_date", "start_date"])


if __name__ == "__main__":
    unittest.main()
