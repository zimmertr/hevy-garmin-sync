"""The command line reports its version and says nothing runs yet."""

import contextlib
import importlib
import io
import os
import runpy
import unittest
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

    def test_no_arguments_says_nothing_runs_yet(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main([]), 0)
        self.assertIn("nothing to run yet", err.getvalue())

    def test_an_unknown_argument_exits_with_a_usage_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_:
            cli.main(["--nope"])
        self.assertEqual(exit_.exception.code, 2)

    def test_python_dash_m_runs_main(self) -> None:
        with mock.patch.object(cli, "main", return_value=0) as main, self.assertRaises(SystemExit) as exit_:
            runpy.run_module("hevy_garmin_sync", run_name="__main__")
        main.assert_called_once_with()
        self.assertEqual(exit_.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
