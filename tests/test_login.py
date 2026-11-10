"""`login` signs in once and prints the value for GARMIN_TOKEN, and nothing else leaves (spec A-2, A-6)."""

import io
import unittest
from unittest import mock

import garminconnect

from hevy_garmin_sync import garmin, login
from tests import fixtures

EMAIL = "someone@example.com"
PASSWORD = "not-a-real-password"


class LoginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.apis: list[fixtures.FakeGarminApi] = []
        self.failure: BaseException | None = None

        def make(*args: object, **kwargs: object) -> fixtures.FakeGarminApi:
            api = fixtures.FakeGarminApi(*args, **kwargs)
            if self.failure:
                api.fail("login", self.failure)
            self.apis.append(api)
            return api

        for patcher in (
            mock.patch.object(garminconnect, "Garmin", make),
            mock.patch("builtins.input", side_effect=[EMAIL]),
            mock.patch("getpass.getpass", return_value=PASSWORD),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_login(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = login.main(out, err)
        return code, out.getvalue(), err.getvalue()

    def test_it_prints_the_token_alone_on_standard_output(self) -> None:
        code, out, err = self.run_login()
        self.assertEqual(code, 0)
        self.assertEqual(out, garmin.encode_token(fixtures.GARMIN_TOKENS) + "\n")
        self.assertIn("Set GARMIN_TOKEN to this value", err)

    def test_the_password_goes_to_the_library_and_nowhere_else(self) -> None:
        _, out, err = self.run_login()
        (api,) = self.apis
        self.assertEqual(api.init_args, (EMAIL, PASSWORD))
        self.assertTrue(api.signed_in)
        for text in (out, err):
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn(EMAIL, text)

    def test_the_library_asks_for_a_code_only_when_garmin_wants_one(self) -> None:
        self.run_login()
        prompt = self.apis[0].init_kwargs["prompt_mfa"]
        with mock.patch("builtins.input", return_value="123456") as ask:
            self.assertEqual(prompt(), "123456")
        ask.assert_called_once_with("Garmin 2FA code: ")
        self.assertEqual(self.apis[0].init_kwargs["retry_attempts"], 0)

    def test_a_wrong_password_exits_non_zero_and_prints_no_token(self) -> None:
        self.failure = garminconnect.GarminConnectAuthenticationError("Authentication failed (401 Unauthorized).")
        code, out, err = self.run_login()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Sign-in failed: Authentication failed", err)
        self.assertIn("run `login` from home", err)

    def test_an_unreachable_garmin_exits_non_zero(self) -> None:
        self.failure = garminconnect.GarminConnectConnectionError("Login failed: connection refused")
        code, out, err = self.run_login()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Sign-in failed", err)

    def test_too_many_attempts_says_to_wait(self) -> None:
        self.failure = garminconnect.GarminConnectTooManyRequestsError("Too many login attempts.")
        code, out, err = self.run_login()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Wait an hour", err)


if __name__ == "__main__":
    unittest.main()
