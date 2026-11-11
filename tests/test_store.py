"""The data folder keeps whole files, private files, and only a hash of what seeded them (spec A-4, A-5)."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hevy_garmin_sync.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "data"
        self.store = Store(self.root)

    def test_a_missing_file_reads_as_none(self) -> None:
        self.assertIsNone(self.store.read("garmin_tokens.json"))

    def test_a_written_file_reads_back_and_the_folder_is_made(self) -> None:
        self.store.write("garmin_tokens.json", "one")
        self.store.write("garmin_tokens.json", "two")
        self.assertEqual(self.store.read("garmin_tokens.json"), "two")
        self.assertEqual(os.listdir(self.root), ["garmin_tokens.json"])

    def test_a_written_file_is_readable_only_by_its_owner(self) -> None:
        self.store.write("garmin_tokens.json", "secret")
        mode = stat.S_IMODE(os.stat(self.root / "garmin_tokens.json").st_mode)
        self.assertEqual(mode, 0o600)

    def test_a_write_is_flushed_to_disk_before_it_replaces_the_file(self) -> None:
        events: list[str] = []
        real_replace = Path.replace

        def replace(self: Path, target: Path) -> Path:
            events.append("rename")
            return real_replace(self, target)

        with (
            mock.patch("os.fsync", side_effect=lambda fd: events.append("fsync")),
            mock.patch.object(Path, "replace", replace),
        ):
            self.store.write("garmin_tokens.json", "secret")
        # The file, then the rename, then the folder that holds the rename.
        self.assertEqual(events, ["fsync", "rename", "fsync"])

    def test_a_write_that_fails_leaves_the_old_file_and_no_scrap(self) -> None:
        self.store.write("garmin_tokens.json", "old")
        with mock.patch("os.fsync", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.store.write("garmin_tokens.json", "new")
        self.assertEqual(self.store.read("garmin_tokens.json"), "old")
        self.assertEqual(os.listdir(self.root), ["garmin_tokens.json"])

    def test_remove_deletes_a_file_and_ignores_a_missing_one(self) -> None:
        self.store.write("hevy_session.json", "x")
        self.store.remove("hevy_session.json")
        self.store.remove("hevy_session.json")
        self.assertIsNone(self.store.read("hevy_session.json"))

    def test_the_seed_is_remembered_as_a_hash_never_as_the_value(self) -> None:
        self.assertFalse(self.store.seeded_by("garmin_tokens.json", "env-value"))
        self.store.mark_seed("garmin_tokens.json", "env-value")
        self.assertTrue(self.store.seeded_by("garmin_tokens.json", "env-value"))
        self.assertFalse(self.store.seeded_by("garmin_tokens.json", "another-value"))
        self.assertNotIn("env-value", (self.root / "garmin_tokens.json.seed").read_text())


if __name__ == "__main__":
    unittest.main()
