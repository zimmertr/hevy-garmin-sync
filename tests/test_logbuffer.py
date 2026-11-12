"""The last lines of the log, kept in memory for the status page (spec W-6)."""

import logging
import unittest

from hevy_garmin_sync import logs
from hevy_garmin_sync.logbuffer import LogBuffer


class LogBufferTest(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = LogBuffer(kept=3)
        self.logger = logging.getLogger("test_logbuffer")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.addHandler(self.buffer)
        self.addCleanup(self.logger.removeHandler, self.buffer)
        self.addCleanup(setattr, self.logger, "propagate", True)

    def test_each_line_keeps_its_time_level_and_message_numbered_in_order(self) -> None:
        self.logger.warning("Garmin refused %r", "Leg Day")
        (line,) = self.buffer.page()["lines"]
        self.assertEqual((line["seq"], line["level"], line["message"]), (1, "WARNING", "Garmin refused 'Leg Day'"))
        self.assertRegex(line["time"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")

    def test_only_the_last_lines_are_kept(self) -> None:
        for i in range(5):
            self.logger.info("line %d", i)
        page = self.buffer.page()
        self.assertEqual([line["message"] for line in page["lines"]], ["line 2", "line 3", "line 4"])
        self.assertEqual([line["seq"] for line in page["lines"]], [3, 4, 5])
        self.assertFalse(page["more"])

    def test_a_page_says_whether_older_lines_are_kept(self) -> None:
        for i in range(3):
            self.logger.info("line %d", i)
        newest = self.buffer.page(size=2)
        self.assertEqual([line["seq"] for line in newest["lines"]], [2, 3])
        self.assertTrue(newest["more"])
        older = self.buffer.page(before=2, size=2)
        self.assertEqual([line["seq"] for line in older["lines"]], [1])
        self.assertFalse(older["more"])

    def test_a_traceback_is_kept_with_its_line(self) -> None:
        try:
            raise ValueError("an unexpected reply")
        except ValueError:
            self.logger.exception("Unexpected error while reading Hevy")
        message = self.buffer.page()["lines"][0]["message"]
        self.assertTrue(message.startswith("Unexpected error while reading Hevy\nTraceback"))
        self.assertIn("ValueError: an unexpected reply", message)

    def test_setup_logs_to_the_buffer_beside_the_stream(self) -> None:
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        self.addCleanup(setattr, root, "handlers", root.handlers[:])
        buffer = LogBuffer()
        logs.setup("INFO", "text", None, buffer)
        self.assertIs(root.handlers[1], buffer)


if __name__ == "__main__":
    unittest.main()
