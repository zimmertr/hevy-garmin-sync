"""Environment variables become the configuration, and a bad one names itself and the fix (spec section 11)."""

import unittest
from pathlib import Path

from hevy_garmin_sync import config
from hevy_garmin_sync.errors import ConfigError

REQUIRED = {"HEVY_API_KEY": "made-up-key"}


class ConfigTest(unittest.TestCase):
    def test_only_the_api_key_is_required_and_the_rest_default(self) -> None:
        loaded = config.load(REQUIRED)
        self.assertEqual(loaded.hevy_api_key, "made-up-key")
        self.assertIsNone(loaded.garmin_token)
        self.assertEqual(loaded.include_folders, ())
        self.assertTrue(loaded.scheduled)
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
                "ENABLE_SCHEDULED_WORKOUTS",
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
        self.assertIn("Trainer off", summary["HEVY_SESSION"])
        self.assertIn("Garmin profile", summary["TZ"])


if __name__ == "__main__":
    unittest.main()
