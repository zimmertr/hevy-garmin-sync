"""scripts/check_upstream.py: Garmin's exercise list and Hevy's spec reduced, compared and rewritten (#26)."""

import http.client
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from scripts import check_upstream as cu
from tests import fixtures

GARMIN = {"BENCH_PRESS": ["BARBELL_BENCH_PRESS", "DUMBBELL_BENCH_PRESS"], "CORE": ["CRUNCH", "PLANK"]}
HEVY = {
    "enums": {
        "equipment": ["barbell", "none"],
        "exercise_template_type": ["reps_only", "weight_reps"],
        "muscle_group": ["abdominals", "chest"],
        "set_type": ["normal", "warmup"],
    },
    "paths": {"/v1/routines": ["get", "post"], "/v1/workouts/events": ["get"]},
}


class FetchTest(unittest.TestCase):
    def test_a_request_carries_only_a_generic_user_agent(self) -> None:
        upstream = fixtures.FakeUpstream()
        self.assertEqual(cu.fetch(cu.GARMIN_URL, upstream), json.dumps(fixtures.garmin_exercise_list()))
        self.assertEqual(upstream.requests[0].header_items(), [("User-agent", cu.USER_AGENT)])
        self.assertEqual(upstream.timeouts, [30])

    def test_a_source_that_cannot_be_reached_is_a_source_error(self) -> None:
        for error in (
            URLError("Name or service not known"),
            HTTPError(cu.HEVY_URL, 503, "Service Unavailable", Message(), None),
            TimeoutError("timed out"),
            http.client.IncompleteRead(b"{"),
        ):
            with self.subTest(error=error):
                upstream = fixtures.FakeUpstream()
                upstream.fail(cu.HEVY_URL, error)
                with self.assertRaisesRegex(cu.SourceError, "could not be fetched"):
                    cu.fetch(cu.HEVY_URL, upstream)

    def test_a_body_that_is_not_utf8_is_a_source_error(self) -> None:
        upstream = fixtures.FakeUpstream()
        upstream.bodies[cu.GARMIN_URL] = b"\xff"
        with self.assertRaises(cu.SourceError):
            cu.fetch(cu.GARMIN_URL, upstream)


class GarminTest(unittest.TestCase):
    def test_keeps_the_category_and_exercise_keys_sorted(self) -> None:
        reduced = cu.reduce_garmin(json.dumps(fixtures.garmin_exercise_list()))
        self.assertEqual(reduced, GARMIN)
        self.assertEqual(list(reduced), sorted(reduced))

    def test_a_list_in_another_shape_is_a_source_error(self) -> None:
        for text in ("<html>", "[]", "{}", '{"categories": []}', '{"categories": {"CORE": []}}', '{"categories": {}}'):
            with self.subTest(text=text), self.assertRaisesRegex(cu.SourceError, "Garmin's exercise list"):
                cu.reduce_garmin(text)


class HevyTest(unittest.TestCase):
    def test_reads_the_spec_out_of_the_docs_script(self) -> None:
        self.assertEqual(cu.spec_from_script(fixtures.hevy_docs_script()), fixtures.hevy_spec())

    def test_keeps_each_path_with_its_methods_and_the_four_enums(self) -> None:
        self.assertEqual(cu.reduce_hevy(fixtures.hevy_docs_script()), HEVY)

    def test_a_script_without_a_spec_is_a_source_error(self) -> None:
        for text in ("window.onload = function() {}", '"swaggerDoc": "/swagger.json"', '"swaggerDoc": {"openapi": '):
            with self.subTest(text=text), self.assertRaisesRegex(cu.SourceError, "swaggerDoc"):
                cu.spec_from_script(text)

    def test_a_spec_without_paths_is_a_source_error(self) -> None:
        for paths in (None, [], {}):
            spec = fixtures.hevy_spec()
            if paths is None:
                del spec["paths"]
            else:
                spec["paths"] = paths
            with self.subTest(paths=paths), self.assertRaisesRegex(cu.SourceError, "paths"):
                cu.reduce_hevy(fixtures.hevy_docs_script(spec))

    def test_a_moved_enum_says_where_the_spec_keeps_its_enums_now(self) -> None:
        spec = fixtures.hevy_spec()
        spec["components"]["schemas"]["MuscleGroups"] = spec["components"]["schemas"].pop("MuscleGroup")
        with self.assertRaises(cu.SourceError) as caught:
            cu.reduce_hevy(fixtures.hevy_docs_script(spec))
        self.assertIn("no enum at components/schemas/MuscleGroup.", str(caught.exception))
        self.assertTrue(str(caught.exception).endswith(", components/schemas/MuscleGroups"))
        self.assertIn("components/schemas/UserInfo/properties/weight_unit", str(caught.exception))

    def test_an_empty_enum_is_a_source_error(self) -> None:
        spec = fixtures.hevy_spec()
        spec["components"]["schemas"]["EquipmentCategory"]["enum"] = []
        with self.assertRaisesRegex(cu.SourceError, "EquipmentCategory"):
            cu.reduce_hevy(fixtures.hevy_docs_script(spec))

    def test_a_spec_with_no_enum_at_all_says_so(self) -> None:
        self.assertEqual(list(cu.enum_paths({"paths": {}, "tags": ["a"]})), [])
        with self.assertRaisesRegex(cu.SourceError, "It has enums at: nowhere"):
            cu.enum_values({"paths": {}}, ("components", "schemas", "MuscleGroup"))


class CompareTest(unittest.TestCase):
    def test_names_each_key_added_and_removed_with_the_keys_above_it(self) -> None:
        fetched = {"BENCH_PRESS": ["BARBELL_BENCH_PRESS"], "CORE": ["CRUNCH", "PLANK", "SIT_UP"], "SQUAT": ["SQUAT"]}
        difference = cu.compare(GARMIN, fetched)
        self.assertEqual(difference.added, ["CORE > SIT_UP", "SQUAT > SQUAT"])
        self.assertEqual(difference.removed, ["BENCH_PRESS > DUMBBELL_BENCH_PRESS"])

    def test_reads_nested_copies_to_the_bottom(self) -> None:
        fetched = json.loads(json.dumps(HEVY))
        fetched["enums"]["set_type"].append("dropset")
        fetched["paths"]["/v1/routines"].remove("post")
        difference = cu.compare(HEVY, fetched)
        self.assertEqual(difference.added, ["enums > set_type > dropset"])
        self.assertEqual(difference.removed, ["paths > /v1/routines > post"])

    def test_a_key_left_empty_still_shows(self) -> None:
        self.assertEqual(cu.compare({}, {"CORE": [], "paths": {}}).added, ["CORE", "paths"])

    def test_the_same_copy_is_no_difference(self) -> None:
        self.assertFalse(cu.compare(HEVY, json.loads(json.dumps(HEVY))))


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.garmin = self.data / "garmin_exercises.json"
        self.hevy = self.data / "hevy_api.json"
        self.garmin.write_text(cu.dump(GARMIN), encoding="utf-8")
        self.hevy.write_text(cu.dump(HEVY), encoding="utf-8")
        self.upstream = fixtures.FakeUpstream()

    def run_main(self, *argv: str) -> tuple[int, str]:
        with redirect_stdout(io.StringIO()) as out:
            code = cu.main(argv, opener=self.upstream, data=self.data)
        return code, out.getvalue()

    def drop_garmin_key(self) -> None:
        self.garmin.write_text(cu.dump(GARMIN | {"CORE": ["CRUNCH"]}), encoding="utf-8")

    def test_matching_copies_exit_0(self) -> None:
        code, out = self.run_main()
        self.assertEqual(code, cu.SAME)
        self.assertEqual(out.count("No difference."), 2)
        self.assertEqual([r.full_url for r in self.upstream.requests], [cu.GARMIN_URL, cu.HEVY_URL])

    def test_a_key_missing_from_the_copy_exits_3_naming_it_in_the_report(self) -> None:
        self.drop_garmin_key()
        report = self.data / "report.md"
        code, out = self.run_main("--report", str(report))
        self.assertEqual(code, cu.DIFFERENT)
        self.assertIn("## Garmin's exercise list\n\n", out)
        self.assertIn("Added (1):\n- `CORE > PLANK`\n", out)
        self.assertIn("## Hevy's API spec\n\n", out)
        self.assertEqual(report.read_text(encoding="utf-8"), out)
        self.assertEqual(self.garmin.read_text(encoding="utf-8"), cu.dump(GARMIN | {"CORE": ["CRUNCH"]}))

    def test_write_puts_the_key_back_and_a_second_check_passes(self) -> None:
        self.drop_garmin_key()
        self.assertEqual(self.run_main("--write")[0], cu.SAME)
        self.assertEqual(self.garmin.read_text(encoding="utf-8"), cu.dump(GARMIN))
        self.assertEqual(self.run_main()[0], cu.SAME)

    def test_write_makes_a_copy_that_is_missing(self) -> None:
        self.hevy.unlink()
        code, out = self.run_main()
        self.assertEqual(code, cu.DIFFERENT)
        self.assertIn("Added (11):", out)
        self.run_main("--write")
        self.assertEqual(json.loads(self.hevy.read_text(encoding="utf-8")), HEVY)

    def test_a_source_that_cannot_be_read_exits_2_and_writes_nothing(self) -> None:
        self.drop_garmin_key()
        self.upstream.fail(cu.HEVY_URL, URLError("Name or service not known"))
        code, out = self.run_main("--write")
        self.assertEqual(code, cu.UNCHECKED)
        self.assertIn("Could not check: https://api.hevyapp.com/docs/swagger-ui-init.js could not be fetched", out)
        self.assertIn("Added (1):", out)
        self.assertEqual(self.garmin.read_text(encoding="utf-8"), cu.dump(GARMIN | {"CORE": ["CRUNCH"]}))

    def test_a_long_list_is_cut_short_for_the_issue(self) -> None:
        self.garmin.write_text(cu.dump({}), encoding="utf-8")
        with mock.patch.object(cu, "LISTED", 1):
            out = self.run_main()[1]
        self.assertIn("Added (4):\n- `BENCH_PRESS > BARBELL_BENCH_PRESS`\n- and 3 more\n", out)


class CommittedCopiesTest(unittest.TestCase):
    def test_each_copy_is_in_the_format_the_rewrite_writes(self) -> None:
        for name in ("garmin_exercises.json", "hevy_api.json"):
            with self.subTest(copy=name):
                text = (cu.DATA / name).read_text(encoding="utf-8")
                self.assertEqual(cu.dump(json.loads(text)), text)


if __name__ == "__main__":
    unittest.main()
