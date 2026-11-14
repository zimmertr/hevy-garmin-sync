"""A preview runs the real loop over made-up accounts, and never reaches Hevy or Garmin (spec W-10)."""

import io
import signal
import tempfile
import unittest
from collections.abc import Callable
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import garminconnect
import requests

from hevy_garmin_sync import app, config, garmin, hevy, preview
from hevy_garmin_sync.exercises import GUESSED, ExerciseMap
from hevy_garmin_sync.hevy_private import HevyPrivate
from hevy_garmin_sync.store import Store
from tests import fixtures

LOGGER = "hevy_garmin_sync"
CREDENTIALS = {
    "HEVY_API_KEY": "made-up-key",
    "GARMIN_TOKEN": garmin.encode_token(fixtures.GARMIN_TOKENS),
    "HEVY_SESSION": fixtures.HEVY_SESSION_COOKIE,
}


class PreviewAppTest(unittest.TestCase):
    """The app as main builds it for a preview, with the clocks pinned, through one full pass."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.utc = fixtures.NOW.astimezone(UTC)
        self.accounts = preview.accounts(self.utc)
        store = Store(Path(folder.name))
        pacing = fixtures.FakeClock()
        loaded = config.load({"PREVIEW_PR": "63", "PREVIEW_COMMIT": "7bc73bc0ffee", "TZ": "America/Los_Angeles"})
        self.app = app.App(
            loaded,
            hevy.Hevy("preview", self.accounts.hevy),  # type: ignore[arg-type]
            garmin.Garmin(self.accounts.garmin, store, sleep=pacing.sleep, clock=pacing),  # type: ignore[arg-type]
            ExerciseMap.load(),
            hevy_private=HevyPrivate(preview.session_tokens(), store, self.accounts.hevy_private),  # type: ignore[arg-type]
            wait=lambda seconds: True,
            clock=lambda: 0.0,
            utcnow=lambda: self.utc,
        )

    def run_once(self) -> dict[str, Any]:
        with self.assertLogs(LOGGER, "INFO"):
            self.assertEqual(self.app.run(), 0)
        return self.app.status

    def test_every_routine_and_trainer_workout_reaches_the_made_up_garmin_but_one(self) -> None:
        status = self.run_once()
        names = sorted(w["workoutName"] for w in self.accounts.garmin.workouts.values())
        self.assertEqual(len(names), 6)
        self.assertFalse(any("Everything Day" in name for name in names))
        refused = [w for w in status["workouts"] if w["refused"]]
        self.assertEqual([w["title"] for w in refused], ["Everything Day"])
        self.assertIn("too many steps", refused[0]["refused"])

    def test_every_service_works_and_trainer_is_on(self) -> None:
        status = self.run_once()
        self.assertEqual({s["name"]: s["state"] for s in status["services"]}, dict.fromkeys(
            ("Hevy", "Hevy Trainer", "Garmin"), "working"
        ))

    def test_the_custom_exercise_goes_by_its_muscle_group(self) -> None:
        status = self.run_once()
        home = next(w for w in status["workouts"] if w["title"] == "Home Shoulders")
        band = next(e for e in home["exercises"] if e["hevy"] == "Band Pull-Apart")
        self.assertEqual((band["chosen_by"], band["garmin"]), (GUESSED, "Lateral Raise"))

    def test_the_status_carries_the_banner(self) -> None:
        self.assertEqual(self.run_once()["preview"], {"pr": "63", "commit": "7bc73bc"})

    def test_a_force_sync_rewrites_the_same_workouts(self) -> None:
        self.run_once()
        before = set(self.accounts.garmin.workouts)
        self.app.requests.ask(force=True)
        self.utc += timedelta(minutes=2)
        self.run_once()
        self.assertEqual(set(self.accounts.garmin.workouts), before)


class PreviewMainTest(unittest.TestCase):
    """main with PREVIEW_PR set ignores every credential and opens no client of its own."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.env = CREDENTIALS | {"DATA_DIR": folder.name, "PREVIEW_PR": "63"}
        self.handlers: dict[int, Callable[..., None]] = {}
        refuse = mock.Mock(side_effect=AssertionError("a preview reached a real service"))
        for patcher in (
            mock.patch("hevy_garmin_sync.server.start"),
            mock.patch.object(signal, "signal", lambda signum, handler: self.handlers.update({signum: handler})),
            mock.patch("hevy_garmin_sync.logs.setup"),
            mock.patch.object(garmin.Garmin, "open", refuse),
            mock.patch.object(HevyPrivate, "open", refuse),
            mock.patch.object(requests, "Session", refuse),
            mock.patch("garminconnect.Garmin", refuse),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_it_runs_on_the_made_up_accounts_even_with_every_credential_set(self) -> None:
        built: list[app.App] = []

        def run(self: app.App) -> int:
            built.append(self)
            return 0

        with mock.patch.object(app.App, "run", run), self.assertLogs(LOGGER, "INFO") as logs:
            self.assertEqual(app.main(self.env, io.StringIO()), 0)
        self.assertIn("A preview of pull request 63", "\n".join(logs.output))
        self.assertIn("HEVY_API_KEY: ignored (a preview)", "\n".join(logs.output))
        self.assertNotIn("made-up-key", "\n".join(logs.output))
        self.assertIsInstance(built[0]._garmin._api, preview.FakeGarminApi)
        self.assertIsNotNone(built[0]._trainer)

    def test_the_session_in_the_data_folder_is_left_alone(self) -> None:
        store = Store(Path(self.env["DATA_DIR"]))
        store.write("hevy_session.json", "{}")
        with mock.patch.object(app.App, "run", return_value=0), self.assertLogs(LOGGER, "INFO"):
            app.main(self.env, io.StringIO())
        self.assertEqual(store.read("hevy_session.json"), "{}")


class AccountsTest(unittest.TestCase):
    def test_each_call_makes_new_accounts(self) -> None:
        first, second = preview.accounts(fixtures.NOW), preview.accounts(fixtures.NOW)
        first.hevy.routines.clear()
        self.assertTrue(second.hevy.routines)

    def test_every_exercise_in_a_routine_or_the_program_has_a_template(self) -> None:
        made_up = preview.accounts(fixtures.NOW)
        ids = {t["id"] for t in made_up.hevy.templates}
        used = {e["exercise_template_id"] for r in made_up.hevy.routines for e in r["exercises"]}
        assert made_up.hevy_private.program is not None
        used |= {e["exercise_template_id"] for t in made_up.hevy_private.program["templates"] for e in t["exercises"]}
        self.assertLessEqual(used, ids)


class RefusalTest(unittest.TestCase):
    """The made-up services refuse what the real ones refuse, as recorded (spec D-10)."""

    def setUp(self) -> None:
        self.made_up = preview.accounts(fixtures.NOW)

    def test_garmin_has_no_workout_by_an_unknown_id(self) -> None:
        with self.assertRaises(garminconnect.GarminConnectConnectionError) as caught:
            self.made_up.garmin.get_workout_by_id(1)
        self.assertEqual(caught.exception.response.status_code, 404)

    def test_hevy_answers_an_unknown_path_with_404(self) -> None:
        self.assertEqual(self.made_up.hevy.get("https://api.hevyapp.com/v1/nothing").status_code, 404)

    def test_the_private_api_refuses_a_refresh_without_a_bearer(self) -> None:
        reply = self.made_up.hevy_private.post("https://api.hevyapp.com/auth/refresh_token", json={})
        self.assertEqual(reply.status_code, 400)

    def test_the_private_api_pages_workouts_by_one_or_three_only(self) -> None:
        reply = self.made_up.hevy_private.get(
            "https://api.hevyapp.com/user_workouts_paged",
            headers={"Authorization": "Bearer hevy-access-1"},
            params={"limit": 2, "offset": 0},
        )
        self.assertEqual(reply.status_code, 400)


if __name__ == "__main__":
    unittest.main()
