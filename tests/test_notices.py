"""NOTICES.md credits every package the image installs directly, at its pinned version."""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# A row of the "Bundled in the image" table: | [name](url) | version | license |
ROW = re.compile(r"^\| \[([^\]]+)\]\([^)]*\) \| (\S+) \| [^|]+ \|$", re.M)


def pins() -> dict[str, str]:
    found = {}
    for line in (REPO / "requirements.in").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            name, _, version = line.partition("==")
            found[name.split("[", 1)[0].lower()] = version
    return found


class NoticesTest(unittest.TestCase):
    def test_the_table_matches_requirements_in(self) -> None:
        text = (REPO / "NOTICES.md").read_text()
        bundled = text.split("## Bundled in the image", 1)
        self.assertEqual(len(bundled), 2, "NOTICES.md has no 'Bundled in the image' section")
        rows = {name.lower(): version for name, version in ROW.findall(bundled[1])}
        expected = pins()
        self.assertTrue(expected, "requirements.in names no pins; the parser stopped matching")
        self.assertEqual(rows, expected)


if __name__ == "__main__":
    unittest.main()
