"""Log lines carry an ISO timestamp, the level and the logger, as text or as JSON (spec O-3)."""

import io
import json
import logging
import unittest
from datetime import datetime

from hevy_garmin_sync import logs


class LogsTest(unittest.TestCase):
    def setUp(self) -> None:
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        library = logging.getLogger("garminconnect").level

        def restore() -> None:
            root.handlers[:] = handlers
            root.setLevel(level)
            logging.getLogger("garminconnect").setLevel(library)

        self.addCleanup(restore)
        self.out = io.StringIO()

    def test_a_text_line_is_timestamp_level_logger_message(self) -> None:
        logs.setup("INFO", "text", self.out)
        logging.getLogger("hevy_garmin_sync.sync").info("Sync: created %d", 2)
        stamp, level, name, message = self.out.getvalue().rstrip("\n").split(" ", 3)
        self.assertIsNotNone(datetime.fromisoformat(stamp).tzinfo)
        self.assertEqual((level, name, message), ("INFO", "hevy_garmin_sync.sync", "Sync: created 2"))

    def test_a_json_line_has_the_same_four_fields(self) -> None:
        logs.setup("INFO", "json", self.out)
        logging.getLogger("hevy_garmin_sync.sync").warning("careful")
        entry = json.loads(self.out.getvalue())
        self.assertEqual(sorted(entry), ["level", "logger", "message", "time"])
        self.assertEqual(
            (entry["level"], entry["logger"], entry["message"]), ("WARNING", "hevy_garmin_sync.sync", "careful")
        )
        self.assertIsNotNone(datetime.fromisoformat(entry["time"]).tzinfo)

    def test_an_exception_is_logged_with_its_traceback_in_both_formats(self) -> None:
        for log_format in ("text", "json"):
            with self.subTest(log_format=log_format):
                out = io.StringIO()
                logs.setup("INFO", log_format, out)
                try:
                    raise RuntimeError("boom")
                except RuntimeError:
                    logging.getLogger("x").exception("it broke")
                self.assertIn("RuntimeError: boom", out.getvalue().replace("\\n", "\n"))
                self.assertIn("it broke", out.getvalue())

    def test_the_level_filters(self) -> None:
        logs.setup("WARNING", "text", self.out)
        logging.getLogger("x").info("quiet")
        logging.getLogger("x").warning("loud")
        self.assertNotIn("quiet", self.out.getvalue())
        self.assertIn("loud", self.out.getvalue())

    def test_setup_replaces_the_handler_instead_of_adding_one(self) -> None:
        logs.setup("INFO", "text", io.StringIO())
        logs.setup("INFO", "text", self.out)
        logging.getLogger("x").info("once")
        self.assertEqual(self.out.getvalue().count("once"), 1)

    def test_the_garmin_library_only_speaks_at_debug(self) -> None:
        logs.setup("INFO", "text", self.out)
        logging.getLogger("garminconnect").error("API call failed")
        self.assertEqual(self.out.getvalue(), "")
        logs.setup("DEBUG", "text", self.out)
        logging.getLogger("garminconnect").error("API call failed")
        self.assertIn("API call failed", self.out.getvalue())

    def test_urllib3_never_logs_urls(self) -> None:
        logs.setup("DEBUG", "text", self.out)
        logging.getLogger("urllib3.connectionpool").debug("GET /userprofile-service/someone")
        self.assertEqual(self.out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
