"""What the image installs is locked and hashed, and the locks match the pins.

`requirements.in` names the image's direct pins, and `requirements.txt` is
pip-compile's lock of them, every indirect package included and every one
hashed. The image installs that lock with `--require-hashes`.
`requirements-dev.txt` is the same lock with the test tools on top,
constrained to the image's, so the suite runs against what ships. `make lock`
writes both, and Dependabot recompiles them. After hevy-trainer-sync's test of
the same name.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# A lock entry is `name==version \` followed by its `--hash=` lines.
LOCK_ENTRY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)(?:\s*\\)?$((?:\n\s+--hash=\S+(?:\s*\\)?)*)", re.M)


def canonical(name: str) -> str:
    # PEP 503: pip treats foo_bar and foo-bar as one name.
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name, _, version = line.partition("==")
        if not version:
            raise AssertionError(f"{path.name}: {line!r} is not an exact pin")
        pins[canonical(name.split("[", 1)[0])] = version.strip()
    return pins


def lock(path: Path) -> dict[str, tuple[str, int]]:
    """name -> (version, number of hashes) for every package the lock pins."""
    return {
        canonical(name): (version, hashes.count("--hash="))
        for name, version, hashes in LOCK_ENTRY.findall(path.read_text())
    }


class LockTest(unittest.TestCase):
    def test_every_direct_pin_is_locked_at_its_version(self) -> None:
        pairs = (("requirements.in", "requirements.txt"), ("requirements-dev.in", "requirements-dev.txt"))
        for source, locked in pairs:
            with self.subTest(source=source):
                pins = direct_pins(REPO / source)
                entries = lock(REPO / locked)
                self.assertTrue(pins, f"{source} names no pins; the parser stopped matching")
                self.assertEqual({name: entries.get(name, (None,))[0] for name in pins}, pins)

    def test_the_dev_lock_installs_what_the_image_installs(self) -> None:
        image, dev = lock(REPO / "requirements.txt"), lock(REPO / "requirements-dev.txt")
        self.assertTrue(image)
        self.assertEqual({name: dev.get(name, (None,))[0] for name in image}, {n: v for n, (v, _) in image.items()})

    def test_every_locked_package_carries_a_hash(self) -> None:
        for locked in ("requirements.txt", "requirements-dev.txt"):
            with self.subTest(lock=locked):
                entries = lock(REPO / locked)
                self.assertTrue(entries, f"{locked} pins nothing; the parser stopped matching")
                self.assertEqual([name for name, (_, hashes) in entries.items() if hashes == 0], [])

    def test_every_install_requires_the_hashes(self) -> None:
        sites = {
            "Dockerfile": "pip install --no-cache-dir --require-hashes -r requirements.txt",
            ".github/workflows/test.yml": "pip install --require-hashes -r requirements-dev.txt",
            ".github/workflows/pr.yml": "pip install --require-hashes -r requirements-dev.txt",
            "Makefile": "pip install -q --root-user-action=ignore --require-hashes -r requirements-dev.txt",
        }
        for path, line in sites.items():
            with self.subTest(path=path):
                text = (REPO / path).read_text()
                self.assertIn(line, text)
                installs = re.findall(r"pip install [^&'\"\n]*-r requirements[\w-]*\.txt", text)
                self.assertEqual([i for i in installs if "--require-hashes" not in i], [])

    def test_the_pip_updates_wait_a_cooldown(self) -> None:
        config = (REPO / ".github" / "dependabot.yml").read_text()
        pip = re.search(r"- package-ecosystem: pip\n(.*?)(?=\n  - package-ecosystem:|\Z)", config, re.S)
        assert pip is not None, "dependabot.yml has no pip entry"
        days = re.search(r"default-days: (\d+)", pip.group(1))
        assert days is not None, "the pip entry has no cooldown"
        self.assertGreater(int(days.group(1)), 0)


if __name__ == "__main__":
    unittest.main()
