"""The command line: its version, the `login` command, and what runs with no arguments."""

import contextlib
import importlib
import io
import json
import os
import runpy
import unittest
import urllib.error
from email.message import Message
from unittest import mock

import hevy_garmin_sync
from hevy_garmin_sync import cli


class VersionTest(unittest.TestCase):
    def tearDown(self) -> None:
        importlib.reload(hevy_garmin_sync)

    def test_the_image_version_comes_from_app_version(self) -> None:
        with mock.patch.dict(os.environ, {"APP_VERSION": "1.2.3"}):
            self.assertEqual(importlib.reload(hevy_garmin_sync).__version__, "1.2.3")

    def test_a_clone_reports_a_dev_version(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "APP_VERSION"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(importlib.reload(hevy_garmin_sync).__version__, "0.0.0+dev")


class CliTest(unittest.TestCase):
    def test_version_prints_the_version_and_exits_zero(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exit_:
            cli.main(["--version"])
        self.assertEqual(exit_.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"hevy-garmin-sync {hevy_garmin_sync.__version__}")

    def test_no_arguments_runs_the_app_and_returns_its_exit_code(self) -> None:
        with mock.patch("hevy_garmin_sync.app.main", return_value=1) as run:
            self.assertEqual(cli.main([]), 1)
        run.assert_called_once_with()

    def test_login_runs_the_sign_in_and_returns_its_exit_code(self) -> None:
        with mock.patch("hevy_garmin_sync.login.main", return_value=1) as sign_in:
            self.assertEqual(cli.main(["login"]), 1)
        sign_in.assert_called_once_with()

    def test_an_unknown_argument_exits_with_a_usage_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_:
            cli.main(["--nope"])
        self.assertEqual(exit_.exception.code, 2)

    def test_python_dash_m_runs_main(self) -> None:
        with mock.patch.object(cli, "main", return_value=0) as main, self.assertRaises(SystemExit) as exit_:
            runpy.run_module("hevy_garmin_sync", run_name="__main__")
        main.assert_called_once_with()
        self.assertEqual(exit_.exception.code, 0)


class SyncTest(unittest.TestCase):
    """`sync` asks the running app through its API, and never calls Hevy or Garmin itself (W-3)."""

    def run_sync(self, *args: str, reply: object = None, env: dict[str, str] | None = None) -> tuple[int, str]:
        out = io.StringIO()
        opened = mock.MagicMock()
        if isinstance(reply, BaseException):
            opened.side_effect = reply
        else:
            opened.return_value.__enter__.return_value = io.BytesIO(json.dumps(reply).encode())
        with (
            mock.patch("urllib.request.urlopen", opened),
            mock.patch.dict(os.environ, env or {}, clear=True),
            contextlib.redirect_stdout(out),
        ):
            code = cli.main(["sync", *args])
        self.requested = opened.call_args.args[0]
        return code, out.getvalue()

    def test_a_sync_is_asked_for_on_this_machine_on_http_port(self) -> None:
        code, out = self.run_sync(reply={"result": "started", "force": False}, env={"HTTP_PORT": "9090"})
        self.assertEqual(code, 0)
        self.assertEqual((self.requested.full_url, self.requested.method), ("http://127.0.0.1:9090/api/sync", "POST"))
        self.assertIn("A sync has started", out)

    def test_force_asks_for_a_forced_sync_on_the_default_port(self) -> None:
        _, out = self.run_sync("--force", reply={"result": "started", "force": True})
        self.assertEqual(self.requested.full_url, "http://127.0.0.1:8080/api/sync?force=true")
        self.assertIn("A forced sync has started", out)

    def test_a_sync_already_running_is_joined(self) -> None:
        code, out = self.run_sync(reply={"result": "joined", "force": False})
        self.assertEqual(code, 0)
        self.assertIn("already running", out)

    def test_within_a_minute_of_the_last_it_says_how_long_to_wait_and_exits_one(self) -> None:
        refused = urllib.error.HTTPError(
            "http://127.0.0.1:8080/api/sync", 429, "Too Many Requests", Message(), io.BytesIO(b'{"seconds": 46}')
        )
        code, out = self.run_sync(reply=refused)
        self.assertEqual(code, 1)
        self.assertIn("Try again in 46 seconds", out)

    def test_another_refusal_says_its_status_and_exits_one(self) -> None:
        refused = urllib.error.HTTPError("http://x", 403, "Forbidden", Message(), io.BytesIO(b""))
        code, out = self.run_sync(reply=refused)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 403", out)

    def test_with_no_app_running_it_says_so_and_exits_one(self) -> None:
        code, out = self.run_sync(reply=urllib.error.URLError(ConnectionRefusedError(111, "refused")))
        self.assertEqual(code, 1)
        self.assertIn("The app isn't running here: nothing answers on port 8080.", out)


if __name__ == "__main__":
    unittest.main()
