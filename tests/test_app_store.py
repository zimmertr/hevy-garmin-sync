"""The newest Hevy app on Apple's App Store, and whether it is past the rules' version (spec F-48a)."""

import unittest
from typing import Any
from unittest import mock

import requests

from hevy_garmin_sync import app_store
from hevy_garmin_sync.hevy import USER_AGENT
from tests import fixtures
from tests.fixtures import FakeResponse, app_store_lookup


class NewestHevyTest(unittest.TestCase):
    def newest(self, reply: FakeResponse | BaseException) -> str | None:
        self.store = fixtures.FakeAppStore(reply)
        return app_store.newest_hevy(self.store)  # type: ignore[arg-type]

    def test_it_reads_the_version_apple_lists(self) -> None:
        self.assertEqual(self.newest(FakeResponse(200, app_store_lookup("3.2.8"))), "3.2.8")
        url, headers, timeout = self.store.requests[0]
        self.assertEqual(url, "https://itunes.apple.com/lookup?id=1458862350")
        self.assertEqual(headers["User-Agent"], USER_AGENT)
        self.assertEqual(timeout, 30)

    def test_without_a_session_it_makes_its_own(self) -> None:
        store = fixtures.FakeAppStore(FakeResponse(200, app_store_lookup("3.2.8")))
        with mock.patch.object(requests, "Session", return_value=store):
            self.assertEqual(app_store.newest_hevy(), "3.2.8")
        self.assertEqual(len(store.requests), 1)

    def test_a_failed_lookup_is_none(self) -> None:
        failures: tuple[FakeResponse | BaseException, ...] = (
            FakeResponse(503, "down"),
            FakeResponse(404, "gone"),
            FakeResponse(200, "not json"),
            requests.ConnectionError("no network"),
        )
        for reply in failures:
            with self.subTest(reply=reply):
                self.assertIsNone(self.newest(reply))

    def test_a_reply_with_no_usable_version_is_none(self) -> None:
        bodies: tuple[Any, ...] = (
            [],
            {"resultCount": 0, "results": []},
            {"results": "none"},
            {"results": ["Hevy"]},
            app_store_lookup(None),
            app_store_lookup(328),
            app_store_lookup("3.2.8-beta"),
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertIsNone(self.newest(FakeResponse(200, body)))


class NewerTest(unittest.TestCase):
    def test_a_later_release_is_newer_part_by_part(self) -> None:
        for version, than in (("3.2.9", "3.2.8"), ("3.2.8.1", "3.2.8"), ("3.2.10", "3.2.9"), ("4.0", "3.9.9")):
            with self.subTest(version=version, than=than):
                self.assertTrue(app_store.newer(version, than))

    def test_the_same_or_an_earlier_release_or_one_that_is_not_a_version_is_not(self) -> None:
        for version, than in (("3.2.8", "3.2.8"), ("3.2.7.1", "3.2.8"), ("3.2.9", "3.2.x"), ("beta", "3.2.8")):
            with self.subTest(version=version, than=than):
                self.assertFalse(app_store.newer(version, than))


if __name__ == "__main__":
    unittest.main()
