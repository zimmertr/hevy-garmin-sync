"""The wait a rate limit asks for, read from its `Retry-After` header (spec O-1, #27)."""

import unittest
from datetime import UTC
from unittest import mock

from hevy_garmin_sync import errors
from tests import fixtures

NOW = fixtures.NOW.astimezone(UTC)  # Friday 16 January 2026, 01:40 UTC


def wait(value: str | None) -> float | None:
    headers = None if value is None else {"Retry-After": value}
    return errors.retry_after(fixtures.FakeResponse(429, {}, headers), lambda: NOW)


class RetryAfterTest(unittest.TestCase):
    def test_a_number_is_seconds(self) -> None:
        self.assertEqual(wait("120"), 120)
        self.assertEqual(wait("3600"), 3600)
        self.assertEqual(wait(" 0 "), 0)

    def test_an_http_date_is_the_time_left_until_it(self) -> None:
        self.assertEqual(wait("Fri, 16 Jan 2026 01:42:00 GMT"), 120)
        self.assertEqual(wait("Fri, 16 Jan 2026 01:42:00 -0000"), 120)

    def test_a_date_already_past_asks_for_no_wait(self) -> None:
        self.assertEqual(wait("Thu, 15 Jan 2026 00:00:00 GMT"), 0)

    def test_no_header_or_one_that_is_neither_gives_none_and_never_raises(self) -> None:
        for value in (None, "", "soon", "-5", "1.5", "²", "Fri, 99 Jan 2026 25:00:00 GMT"):
            with self.subTest(value=value):
                self.assertIsNone(wait(value))

    def test_a_reply_without_headers_gives_none(self) -> None:
        self.assertIsNone(errors.retry_after(None))
        self.assertIsNone(errors.retry_after(object()))

    def test_by_default_a_date_is_measured_from_the_current_time(self) -> None:
        with mock.patch.object(errors, "datetime") as clock:
            clock.now.return_value = NOW
            self.assertEqual(errors.retry_after(fixtures.rate_limited("Fri, 16 Jan 2026 01:42:00 GMT")), 120)
        clock.now.assert_called_once_with(UTC)


if __name__ == "__main__":
    unittest.main()
