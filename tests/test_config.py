"""Environment variables become the configuration, and a bad one names itself and the fix (spec section 11)."""

import re
import unittest
from pathlib import Path

from hevy_garmin_sync import config
from hevy_garmin_sync.errors import ConfigError
from hevy_garmin_sync.exercises import GarminExercise

REQUIRED = {"HEVY_API_KEY": "made-up-key"}


class ConfigTest(unittest.TestCase):
    def test_only_the_api_key_is_required_and_the_rest_default(self) -> None:
        loaded = config.load(REQUIRED)
        self.assertEqual(loaded.hevy_api_key, "made-up-key")
        self.assertIsNone(loaded.garmin_token)
        self.assertEqual(loaded.include_folders, ())
        self.assertTrue(loaded.scheduled)
        self.assertTrue(loaded.previous_values)
        self.assertIsNone(loaded.hevy_session)
        self.assertEqual(loaded.poll_seconds, 60)
        self.assertIsNone(loaded.zone)
        self.assertEqual(loaded.data_dir, Path("data"))
        self.assertEqual((loaded.log_level, loaded.log_format), ("INFO", "text"))

    def test_every_variable_is_read(self) -> None:
        loaded = config.load(
            REQUIRED
            | {
                "GARMIN_TOKEN": " token ",
                "INCLUDE_HEVY_FOLDERS": " Push Pull Legs , 42,, ",
                "ENABLE_SCHEDULED_WORKOUTS": "False",
                "ENABLE_PREVIOUS_VALUES": " FALSE ",
                "HEVY_SESSION": "cookie",
                "HEVY_POLL_INTERVAL_SECONDS": "10",
                "TZ": "America/Los_Angeles",
                "DATA_DIR": "/data",
                "LOG_LEVEL": "debug",
                "LOG_FORMAT": "JSON",
            }
        )
        self.assertEqual(loaded.garmin_token, "token")
        self.assertEqual(loaded.include_folders, ("Push Pull Legs", "42"))
        self.assertFalse(loaded.scheduled)
        self.assertFalse(loaded.previous_values)
        self.assertEqual(loaded.hevy_session, "cookie")
        self.assertEqual(loaded.poll_seconds, 10)
        self.assertEqual(loaded.zone.key if loaded.zone else None, "America/Los_Angeles")
        self.assertEqual(loaded.data_dir, Path("/data"))
        self.assertEqual((loaded.log_level, loaded.log_format), ("DEBUG", "json"))

    def test_an_empty_value_counts_as_unset(self) -> None:
        loaded = config.load(REQUIRED | {"INCLUDE_HEVY_FOLDERS": " ", "HEVY_SESSION": "", "TZ": "", "GARMIN_TOKEN": ""})
        self.assertEqual(loaded.include_folders, ())
        self.assertIsNone(loaded.hevy_session)
        self.assertIsNone(loaded.zone)
        self.assertIsNone(loaded.garmin_token)

    def test_a_bad_value_names_its_variable(self) -> None:
        cases = {
            "HEVY_API_KEY": [""],
            "ENABLE_SCHEDULED_WORKOUTS": ["yes", "1"],
            "ENABLE_PREVIOUS_VALUES": ["no", "0"],
            "HEVY_POLL_INTERVAL_SECONDS": ["9", "0", "-60", "1.5", "a minute", "٦٠"],
            "TZ": ["Mars/Olympus_Mons", "../etc/passwd"],
            "LOG_LEVEL": ["LOUD"],
            "LOG_FORMAT": ["xml"],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ConfigError, f"^{name} "):
                    config.load(REQUIRED | {name: value})

    def test_the_summary_shows_every_variable_and_no_secret(self) -> None:
        secrets = {"HEVY_API_KEY": "made-up-key", "GARMIN_TOKEN": "made-up-token", "HEVY_SESSION": "made-up-cookie"}
        summary = config.load(secrets | {"INCLUDE_HEVY_FOLDERS": "PPL", "TZ": "America/Los_Angeles"}).summary()
        self.assertEqual(
            list(summary),
            [
                "HEVY_API_KEY",
                "GARMIN_TOKEN",
                "INCLUDE_HEVY_FOLDERS",
                "CUSTOM_EXERCISE_MAP",
                "ENABLE_SCHEDULED_WORKOUTS",
                "ENABLE_PREVIOUS_VALUES",
                "HEVY_SESSION",
                "HEVY_POLL_INTERVAL_SECONDS",
                "TZ",
                "DATA_DIR",
                "LOG_LEVEL",
                "LOG_FORMAT",
            ],
        )
        for secret in secrets.values():
            self.assertNotIn(secret, " ".join(summary.values()))
        self.assertEqual(summary["INCLUDE_HEVY_FOLDERS"], "PPL")
        self.assertEqual(summary["TZ"], "America/Los_Angeles")

    def test_the_summary_says_what_an_unset_variable_means(self) -> None:
        summary = config.load(REQUIRED).summary()
        self.assertIn("unset", summary["GARMIN_TOKEN"])
        self.assertIn("all routines", summary["INCLUDE_HEVY_FOLDERS"])
        self.assertIn("by muscle group and equipment", summary["CUSTOM_EXERCISE_MAP"])
        self.assertIn("Trainer off", summary["HEVY_SESSION"])
        self.assertIn("Garmin profile", summary["TZ"])


class CustomExerciseMapTest(unittest.TestCase):
    """CUSTOM_EXERCISE_MAP: title-or-id=CATEGORY/NAME, comma-separated, each pair one Garmin has (C-11, #24)."""

    def load(self, value: str) -> dict[str, GarminExercise]:
        return dict(config.load(REQUIRED | {"CUSTOM_EXERCISE_MAP": value}).custom_exercises)

    def test_unset_or_empty_is_no_entries(self) -> None:
        self.assertEqual(config.load(REQUIRED).custom_exercises, {})
        self.assertEqual(self.load(" , "), {})

    def test_each_entry_is_trimmed_and_split_on_its_last_equals_sign(self) -> None:
        loaded = self.load(
            " My Cable Raise = LATERAL_RAISE / CABLE_FRONT_RAISE ,, a1b2c3d4=CURL/CURL, Reps=Max=PLANK/PLANK "
        )
        self.assertEqual(
            loaded,
            {
                "My Cable Raise": GarminExercise("LATERAL_RAISE", "CABLE_FRONT_RAISE"),
                "a1b2c3d4": GarminExercise("CURL", "CURL"),
                "Reps=Max": GarminExercise("PLANK", "PLANK"),
            },
        )

    def test_an_entry_not_in_the_form_exits_naming_it(self) -> None:
        for entry in ("My Raise", "=CURL/CURL", "My Raise=", "My Raise=CURL", "My Raise=CURL/", "My Raise=/CURL"):
            with (
                self.subTest(entry=entry),
                self.assertRaisesRegex(ConfigError, f"^CUSTOM_EXERCISE_MAP entry '{re.escape(entry)}' is not"),
            ):
                self.load(f"Fine=CURL/CURL,{entry}")
        with self.assertRaisesRegex(ConfigError, "is not title-or-id=CATEGORY/NAME"):
            self.load("My Raise=CURL/CURL/CURL")

    def test_a_pair_garmin_does_not_have_exits_naming_the_pair(self) -> None:
        for pair in ("CURL/NO_SUCH_CURL", "NO_SUCH_CATEGORY/CURL", "curl/curl"):
            with (
                self.subTest(pair=pair),
                self.assertRaisesRegex(ConfigError, f"^CUSTOM_EXERCISE_MAP names {pair}, which Garmin doesn't have"),
            ):
                self.load(f"My Raise={pair}")

    def test_an_exercise_named_twice_exits(self) -> None:
        with self.assertRaisesRegex(ConfigError, "^CUSTOM_EXERCISE_MAP names 'My Raise' twice"):
            self.load("My Raise=CURL/CURL, My Raise =PLANK/PLANK")

    def test_the_summary_counts_the_entries_and_never_shows_one(self) -> None:
        one = config.load(REQUIRED | {"CUSTOM_EXERCISE_MAP": "My Raise=CURL/CURL"}).summary()
        two = config.load(REQUIRED | {"CUSTOM_EXERCISE_MAP": "My Raise=CURL/CURL,My Hold=PLANK/PLANK"}).summary()
        self.assertEqual(one["CUSTOM_EXERCISE_MAP"], "set (1 entry)")
        self.assertEqual(two["CUSTOM_EXERCISE_MAP"], "set (2 entries)")
        self.assertNotIn("My Raise", " ".join(two.values()))


if __name__ == "__main__":
    unittest.main()
