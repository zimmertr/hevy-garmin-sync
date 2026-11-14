"""What the image installs is locked and hashed, and the locks match the pins.

`requirements.in` names the image's direct pins, and `requirements.txt` is
pip-compile's lock of them, every indirect package included and every one
hashed. The image installs that lock with `--require-hashes`.
`requirements-dev.txt` is the same lock with the test tools on top,
constrained to the image's, so the suite runs against what ships. `make lock`
writes both, and Renovate recompiles them. After hevy-trainer-sync's test of
the same name.
"""

import json
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

    def test_renovate_recompiles_both_locks_under_the_shared_wait(self) -> None:
        config = json.loads((REPO / ".github" / "renovate.json").read_text())
        # The seven-day wait is the preset's (zimmertr/yggdrasil record 0056).
        # A config that stops extending it merges a release the day it ships.
        self.assertIn("github>zimmertr/yggdrasil//defaults/renovate", config["extends"])
        self.assertNotIn("minimumReleaseAge", json.dumps(config))
        patterns = [re.compile(p.strip("/")) for p in config["pip-compile"]["managerFilePatterns"]]
        for locked in ("requirements.txt", "requirements-dev.txt"):
            with self.subTest(lock=locked):
                self.assertTrue(any(p.search(locked) for p in patterns), f"Renovate's pip-compile skips {locked}")
        # pip_requirements would bump a lock's pin and leave its hashes stale.
        self.assertIs(config["pip_requirements"]["enabled"], False)

    def test_renovate_reads_every_python_pin_and_they_agree(self) -> None:
        # A Python minor moves in one PR (record 0014). A custom rule that stops
        # matching its file leaves that pin behind, to be moved by hand.
        config = json.loads((REPO / ".github" / "renovate.json").read_text())
        versions: dict[str, str] = {}
        for manager in config["customManagers"]:
            patterns = [re.compile(p.strip("/")) for p in manager["managerFilePatterns"]]
            # Renovate writes a named group as (?<name>...), Python as (?P<name>...).
            strings = [re.compile(s.replace("(?<", "(?P<")) for s in manager["matchStrings"]]
            candidates = ("mypy.ini", "requirements.txt", "requirements-dev.txt")
            files = [f for f in candidates if any(p.search(f) for p in patterns)]
            self.assertNotEqual(files, [], manager["description"])
            for name in files:
                with self.subTest(file=name):
                    found = strings[0].search((REPO / name).read_text())
                    assert found is not None, f"Renovate reads no Python version in {name}"
                    versions[name] = found.group("currentValue")
        dockerfile = re.search(r"^FROM python:(\d+\.\d+)-", (REPO / "Dockerfile").read_text(), re.M)
        makefile = re.search(r"^PYTHON_IMAGE := python:(\d+\.\d+)-", (REPO / "Makefile").read_text(), re.M)
        assert dockerfile is not None and makefile is not None
        versions["Dockerfile"], versions["Makefile"] = dockerfile.group(1), makefile.group(1)
        for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
            for found in re.finditer(r'python-version: "(\d+\.\d+)"', workflow.read_text()):
                versions[workflow.name] = found.group(1)
        self.assertEqual(len(set(versions.values())), 1, versions)
        group = [r for r in config["packageRules"] if r.get("groupName") == "Python"]
        self.assertEqual([r["matchDepNames"] for r in group], [["python"]])

    def test_renovate_can_read_each_locks_header(self) -> None:
        # Renovate recompiles a lock with the command in its header, and stops
        # at an option it doesn't know. pip-tools 7.5.3 wrote --no-index there.
        known = {"--allow-unsafe", "--generate-hashes", "--strip-extras", "--output-file"}
        for locked in ("requirements.txt", "requirements-dev.txt"):
            with self.subTest(lock=locked):
                command = re.search(r"^#    pip-compile (.+)$", (REPO / locked).read_text(), re.M)
                assert command is not None, f"{locked} has no pip-compile header"
                options = {word.split("=", 1)[0] for word in command.group(1).split() if word.startswith("-")}
                self.assertEqual(options - known, set())


if __name__ == "__main__":
    unittest.main()
