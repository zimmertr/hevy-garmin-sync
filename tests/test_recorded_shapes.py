"""The fakes answer in the shapes Hevy and Garmin answered in (spec D-10).

tests/data/recorded_shapes.json is what the live checks recorded, trimmed to the replies the fakes
build: keys and type names, never a value. Garmin's and Hevy Trainer's are from `make live-check` on
2026-11-10, Hevy's public API's from `make live-check-hevy` on 2026-11-11. This runs the live check over
the fakes and compares what it records with that file, so a builder in tests/fixtures.py that drifts
from a real reply fails here.
"""

import io
import json
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest import mock

import garminconnect

from hevy_garmin_sync import garmin, workout
from hevy_garmin_sync.store import Store
from scripts import live_check as lc
from tests import fixtures

SHAPES = Path(__file__).parent / "data" / "recorded_shapes.json"
# Fields Hevy sends on some items only: a routine set's `rep_range` comes with a rep range (docs/DATA.md),
# and the set recorded on 2026-11-11 had none.
OPTIONAL = {"rep_range"}
# Hevy sends a whole weight as an int and another as a float, so the two are one type here.
NUMBER = ("int", "float")  # a tuple, since a shape compared with it may be a dict


def drift(recorded: Any, built: Any, path: str = "") -> list[str]:
    """Every place `built` differs from `recorded`, two shapes as `live_check.shape` writes them.

    A field recorded or built as None may hold anything, since it is null in one reply and set in
    another. An empty list says nothing about its items. `<key>` is a key the recording hid, so it is
    never compared.
    """
    if "NoneType" in (recorded, built):
        return []
    if isinstance(recorded, dict) and isinstance(built, dict):
        found = []
        for key in sorted((recorded.keys() | built.keys()) - {"<key>"}):
            here = f"{path}.{key}"
            if key not in built:
                found.append(f"{here}: recorded, missing from the fake")
            elif key not in recorded:
                if key not in OPTIONAL:
                    found.append(f"{here}: in the fake, not in the recorded reply")
            else:
                found += drift(recorded[key], built[key], here)
        return found
    if isinstance(recorded, list) and isinstance(built, list):
        return drift(recorded[0], built[0], f"{path}[0]") if recorded and built else []
    if recorded == built or (recorded in NUMBER and built in NUMBER):
        return []
    return [f"{path}: recorded {recorded}, the fake gives {built}"]


def built_shapes() -> dict[str, Any]:
    """What `live_check.record` saves when every reply comes from the fakes."""
    hevy_api = fixtures.FakeHevyApi()
    hevy_api.folders = [fixtures.hevy_folder(1, "Made Up")]
    hevy_api.routines = [fixtures.hevy_routine("r-1", "Made Up", 1)]
    hevy_api.events = [fixtures.hevy_workout_event("w-1", "T-BENCH", "Bench Press (Barbell)")]
    hevy_api.history = {"T-BENCH": [fixtures.hevy_history_set(60.0, 8, "2026-01-15T17:00:00+00:00")]}
    private_api = fixtures.FakeHevyPrivateApi()
    upper = fixtures.trainer_template("t-upper", "upper_2x_a", [fixtures.trainer_exercise("T-GOBLET")])
    private_api.program = fixtures.trainer_program([fixtures.lower_template(), upper])
    private_api.workouts = [fixtures.logged_lower(fixtures.PROGRAM_START)]
    garmin_api = fixtures.FakeGarminApi()
    # One of the app's own workouts on today, first, as the live run found: a weighted set, then a rest.
    lifted = workout.Exercise("Made Up", "SQUAT", "GOBLET_SQUAT", (workout.Set(reps=8, weight_kg=20.0),))
    body = workout.build(workout.Workout(workout.TRAINER, "t-lower", "Made Up", (lifted,)), "statute_us")
    app_workout = garmin_api.upload_workout(body | {"description": "made up"})
    garmin_api.schedule_workout(app_workout["workoutId"], fixtures.TODAY.isoformat())
    clock = fixtures.FakeClock()

    def open_garmin(token: str | None, store: Store) -> lc.CheckGarmin:
        lc.CheckGarmin.open(token, store)
        return lc.CheckGarmin(garmin_api, store, sleep=clock.sleep, clock=clock)  # type: ignore[arg-type]

    patched = mock.patch.object(garminconnect, "Garmin", lambda **_: garmin_api)
    with tempfile.TemporaryDirectory() as folder, patched:
        code = lc.record(
            {"HEVY_API_KEY": "made-up-key", "HEVY_SESSION": fixtures.HEVY_SESSION_COOKIE},
            Path(folder),
            io.StringIO(),
            sign_in=lambda: garmin.encode_token(fixtures.GARMIN_TOKENS),
            open_garmin=open_garmin,
            hevy_session=hevy_api,  # type: ignore[arg-type]
            private_session=private_api,  # type: ignore[arg-type]
            utcnow=lambda: fixtures.NOW.astimezone(UTC),
        )
        assert code == 0, "the live check failed over the fakes"
        saved: dict[str, Any] = json.loads((Path(folder) / lc.RECORDED).read_text(encoding="utf-8"))
    return saved


class RecordedShapesTest(unittest.TestCase):
    recorded: dict[str, Any]
    built: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.recorded = json.loads(SHAPES.read_text(encoding="utf-8"))
        cls.built = built_shapes()

    def test_every_recorded_reply_is_the_shape_its_fake_answers_in(self) -> None:
        for service, replies in self.recorded.items():
            for name, recorded in replies.items():
                with self.subTest(reply=f"{service}.{name}"):
                    built = self.built[service][name]
                    # An empty list passes any comparison, so the fake must fill every list Hevy filled.
                    self.assertEqual(bool(built), bool(recorded))
                    self.assertEqual(drift(recorded, built), [])

    def test_a_recorded_reply_holds_no_value(self) -> None:
        def leaves(node: Any) -> set[str]:
            children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else None
            if children is None:
                return {str(node)}
            found: set[str] = set()
            for child in children:
                found |= leaves(child)
            return found

        self.assertLessEqual(leaves(self.recorded), {"str", "int", "float", "bool", "NoneType"})


class DriftTest(unittest.TestCase):
    def test_it_names_each_difference_and_lets_nulls_empty_lists_and_numbers_pass(self) -> None:
        recorded = {"a": "int", "b": "str", "c": [{"d": "bool"}], "e": "NoneType", "f": [], "<key>": "str", "n": "int"}
        built = {
            "a": "str",
            "c": [{"d": "bool", "x": "int", "rep_range": "NoneType"}],
            "e": {"g": "int"},
            "f": ["int"],
            "y": "NoneType",
            "n": "float",
        }
        self.assertEqual(
            drift(recorded, built),
            [
                ".a: recorded int, the fake gives str",
                ".b: recorded, missing from the fake",
                ".c[0].x: in the fake, not in the recorded reply",
                ".y: in the fake, not in the recorded reply",
            ],
        )


if __name__ == "__main__":
    unittest.main()
