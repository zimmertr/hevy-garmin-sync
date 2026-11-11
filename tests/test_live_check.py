"""scripts/live_check.py: the one run by hand for #22, #24 and #6, over the fakes, never the network."""

import io
import json
import tempfile
import unittest
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import garminconnect
import requests

from hevy_garmin_sync import garmin, trainer, workout
from hevy_garmin_sync.errors import Refused
from hevy_garmin_sync.store import Store
from scripts import live_check as lc
from tests import fixtures
from tests.fixtures import (
    hevy_exercise,
    hevy_folder,
    hevy_routine,
    hevy_set,
    trainer_exercise,
    trainer_program,
    trainer_template,
)

API_KEY = "made-up-key"
TOKEN = garmin.encode_token(fixtures.GARMIN_TOKENS)
# Every value the fakes hold that must never reach the output or the saved file.
SECRETS = (
    API_KEY,
    fixtures.HEVY_SESSION_COOKIE,
    "hevy-access-1",
    "hevy-refresh-1",
    TOKEN,
    "access-1",
    "someone",
    "My Own Folder",
    "My Own Routine",
    "r-mine",
    "T-BENCH",
    "Bench Press",
    "t-upper",
    "upper_2x_a",
    "A1B2-C3D4",
)


class LiveCheckCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name) / "live-check"
        self.store = Store(self.folder)
        self.hevy_api = fixtures.FakeHevyApi()
        self.hevy_api.folders = [hevy_folder(42, "My Own Folder")]
        self.hevy_api.routines = [
            hevy_routine("r-mine", "My Own Routine", 42, [hevy_exercise("T-BENCH", "Bench Press", [hevy_set(reps=8)])])
        ]
        self.private_api = fixtures.FakeHevyPrivateApi()
        self.private_api.units = {"A1B2-C3D4": {"unit": "kg"}}
        self.private_api.program = trainer_program(
            [trainer_template("t-upper", "upper_2x_a", []), trainer_template("t-lower", "lower_2x_a", [])],
            next_workout_index=1,
        )
        self.garmin_api = fixtures.FakeGarminApi()
        self.clock = fixtures.FakeClock()
        self.tokens: list[str | None] = []
        self.asked: list[str] = []
        self.answers: list[str] = []
        patcher = mock.patch.object(garminconnect, "Garmin", lambda **_: self.garmin_api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_garmin(self, token: str | None, store: Store) -> lc.CheckGarmin:
        """The script's own `CheckGarmin.open`, then the same fake on a clock that moves only when it waits."""
        self.tokens.append(token)
        lc.CheckGarmin.open(token, store)
        return lc.CheckGarmin(
            self.garmin_api,  # type: ignore[arg-type]
            store,
            sleep=self.clock.sleep,
            clock=self.clock,
        )

    def ask(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0) if self.answers else ""

    def record(self, env: dict[str, str] | None = None, sign_in: Any = lambda: TOKEN) -> tuple[int, str]:
        out = io.StringIO()
        code = lc.record(
            {"HEVY_API_KEY": API_KEY, "HEVY_SESSION": fixtures.HEVY_SESSION_COOKIE} if env is None else env,
            self.folder,
            out,
            ask=self.ask,
            sign_in=sign_in,
            open_garmin=self.open_garmin,
            hevy_session=self.hevy_api,  # type: ignore[arg-type]
            private_session=self.private_api,  # type: ignore[arg-type]
            utcnow=lambda: fixtures.NOW.astimezone(UTC),
        )
        return code, out.getvalue()

    def record_hevy(self, env: dict[str, str] | None = None) -> tuple[int, str]:
        out = io.StringIO()
        code = lc.record_hevy(
            {"HEVY_API_KEY": API_KEY, "HEVY_SESSION": fixtures.HEVY_SESSION_COOKIE} if env is None else env,
            self.folder,
            out,
            ask=self.ask,
            hevy_session=self.hevy_api,  # type: ignore[arg-type]
            private_session=self.private_api,  # type: ignore[arg-type]
            utcnow=lambda: fixtures.NOW.astimezone(UTC),
        )
        return code, out.getvalue()

    def cleanup(self) -> tuple[int, str]:
        out = io.StringIO()
        code = lc.cleanup(
            self.folder, out, open_garmin=self.open_garmin, utcnow=lambda: fixtures.NOW.astimezone(UTC)
        )
        return code, out.getvalue()

    def names(self) -> list[str]:
        return sorted(w["workoutName"] for w in self.garmin_api.workouts.values())

    def saved(self) -> dict[str, Any]:
        recorded: dict[str, Any] = json.loads(self.store.read(lc.RECORDED) or "{}")
        return recorded


class RecordTest(LiveCheckCase):
    def created(self) -> list[int]:
        ids: list[int] = json.loads(self.store.read(lc.CREATED) or "{}")["workouts"]
        return ids

    def test_it_puts_the_set_workout_on_today_sends_it_to_the_watch_and_leaves_no_probe(self) -> None:
        code, out = self.record()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), [lc.SET_WORKOUT])
        ((set_id, _),) = self.garmin_api.workouts.items()
        self.assertEqual([e["calendarDate"] for e in self.garmin_api.entries.values()], [fixtures.TODAY.isoformat()])
        self.assertEqual(self.garmin_api.pushed, [set_id])
        self.assertEqual(self.created(), [set_id])
        self.assertIn(f"{lc.SET_WORKOUT} is on today's calendar and on its way to the watch", out)

    def test_the_set_workout_is_one_plain_set_then_a_repeat_group_then_a_superset_group(self) -> None:
        body = lc.set_body("statute_us")
        steps = body["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(
            [s["type"] for s in steps], ["ExecutableStepDTO", "ExecutableStepDTO", "RepeatGroupDTO", "RepeatGroupDTO"]
        )
        self.assertEqual([s.get("numberOfIterations") for s in steps[2:]], [3, 2])
        superset = [s["exerciseName"] for s in steps[3]["workoutSteps"] if "exerciseName" in s]
        self.assertEqual(superset, ["CRUNCH", "SQUAT"])
        first = steps[0]
        self.assertEqual((first["category"], first["exerciseName"]), ("HYPEREXTENSION", "HYPEREXTENSION"))
        self.assertEqual((first["endCondition"]["conditionTypeKey"], first["endConditionValue"]), ("reps", 10.0))
        self.assertNotIn("weightValue", first)

    def test_garmin_writes_are_a_second_apart_as_the_app_spaces_them(self) -> None:
        self.record()
        kinds = ("upload_workout", "schedule_workout", "push_workout_to_device", "delete_workout")
        writes = [call for call in self.garmin_api.calls if call in kinds]
        self.assertEqual(
            writes, ["upload_workout", "schedule_workout", "push_workout_to_device", "upload_workout", "delete_workout"]
        )
        self.assertEqual(self.clock.sleeps, [1.0] * 4)  # O-1b

    def test_no_check_workout_carries_the_apps_description(self) -> None:
        self.assertIsNone(workout.owner(lc.DESCRIPTION))
        self.record()
        for stored in self.garmin_api.workouts.values():
            self.assertEqual(stored["description"], lc.DESCRIPTION)
            self.assertIsNone(workout.owner(stored["description"]))

    def test_it_prints_the_exercise_sent_and_the_one_garmin_stored_for_every_set(self) -> None:
        _, out = self.record()
        lines = self.saved()["garmin"]["sets"]
        self.assertEqual(
            lines,
            [
                # Garmin stored this pair with an empty exercise name on 2026-11-10, and the fake does too.
                "Set 1: sent HYPEREXTENSION / HYPEREXTENSION, Garmin stored HYPEREXTENSION / ",
                "Set 2: sent CURL / CURL, Garmin stored CURL / CURL",
                "Set 3: sent CRUNCH / CRUNCH, Garmin stored CRUNCH / CRUNCH",
                "Set 4: sent SQUAT / SQUAT, Garmin stored SQUAT / SQUAT",
            ],
        )
        self.assertIn(f"{lc.SET_WORKOUT}:\n" + "\n".join(lines) + "\n", out)

    def test_it_keeps_the_shape_of_each_kind_of_stored_step_groups_and_their_steps_included(self) -> None:
        _, out = self.record()
        kinds = self.saved()["garmin"]["stored_steps"]
        self.assertEqual(
            sorted(kinds), ["group.repeat", "in_group.interval", "in_group.rest", "step.interval", "step.rest"]
        )
        self.assertNotIn("workoutSteps", kinds["group.repeat"])
        self.assertEqual(kinds["group.repeat"]["numberOfIterations"], "int")
        self.assertEqual(kinds["in_group.interval"]["exerciseName"], "str")
        self.assertIn("Kinds of step Garmin stored: group.repeat, in_group.interval, in_group.rest", out)

    def test_a_step_with_no_step_type_or_an_odd_one_is_kept_under_a_hidden_key(self) -> None:
        stored = {"workoutSegments": [{"workoutSteps": [{"type": "x"}, {"stepType": {"stepTypeKey": "Odd-1"}}]}]}
        self.assertEqual(lc.step_shapes(stored), {"step.<key>": {"type": "str"}})
        self.assertEqual(lc.step_shapes({}), {})

    def test_the_step_probe_is_made_and_deleted_at_once_when_garmin_takes_it(self) -> None:
        _, out = self.record()
        self.assertEqual(self.saved()["garmin"]["step_cap"], ["250 steps: accepted"])
        self.assertNotIn(lc.STEPS_WORKOUT, self.names())
        self.assertIn(f"{lc.STEPS_WORKOUT} (the step cap, each made and deleted at once):\n250 steps: accepted\n", out)
        self.assertEqual(len(self.garmin_api.entries), 1)
        self.assertEqual(len(self.garmin_api.pushed), 1)

    def test_each_probe_size_is_its_steps_and_no_repeat_group_shortens_it(self) -> None:
        for size in lc.STEP_SIZES:
            with self.subTest(size=size):
                body = lc.steps_body(size, None)
                self.assertEqual(workout.step_count(body), size)
                steps = body["workoutSegments"][0]["workoutSteps"]
                self.assertNotIn("RepeatGroupDTO", {s["type"] for s in steps})
                self.assertEqual(body["workoutName"], lc.STEPS_WORKOUT)

    def test_a_refused_size_prints_garmins_status_and_reason_and_the_probe_steps_down(self) -> None:
        self.garmin_api.max_steps = 120
        _, out = self.record()
        reason = "made up: the workout has too many steps"
        self.assertEqual(
            self.saved()["garmin"]["step_cap"],
            [f"250 steps: refused (Refused, HTTP 400: API Error 400 - {reason})", "100 steps: accepted"],
        )
        self.assertIn(reason, out)
        self.assertEqual(self.names(), [lc.SET_WORKOUT])

    def test_every_size_refused_or_failing_is_recorded_and_the_run_still_finishes(self) -> None:
        self.garmin_api.max_steps = 10
        self.garmin_api.too_many_steps = fixtures.garmin_error(500)
        code, _ = self.record()
        self.assertEqual(code, 0)
        failed = "refused (Unavailable, HTTP 500: API Error 500)"
        self.assertEqual(self.saved()["garmin"]["step_cap"], [f"{n} steps: {failed}" for n in lc.STEP_SIZES])
        self.assertEqual(self.created(), [next(iter(self.garmin_api.workouts))])

    def test_a_refusal_with_no_reply_says_so(self) -> None:
        self.assertEqual(lc.refusal(Refused("unexpected reply")), "Refused: unexpected reply")
        self.assertEqual(len(lc.refusal(Refused("x" * 900))), len("Refused: ") + 500)

    def test_a_probe_garmin_takes_but_fails_to_delete_is_left_in_the_id_file_for_cleanup(self) -> None:
        self.garmin_api.fail("delete_workout", fixtures.garmin_error(500))
        code, out = self.record()
        self.assertEqual(code, 1)
        self.assertIn("Garmin failed partway (Unavailable). 2 check workouts are left in Garmin", out)
        self.assertEqual(sorted(self.created()), sorted(self.garmin_api.workouts))
        self.assertEqual(sorted(self.names()), [lc.SET_WORKOUT, lc.STEPS_WORKOUT])

    def test_a_stored_workout_nested_another_way_lists_every_step_found(self) -> None:
        sent = lc.set_body(None)
        stored = {"workoutSegments": [{"steps": list(lc.sets(json.loads(json.dumps(sent))))}]}
        lines = lc.compare(sent, stored)
        counts = "The counts differed: 4 steps sent, 0 found where the app reads them."
        self.assertEqual(lines[0], f"{counts} Every step found anywhere in the stored workout:")
        self.assertEqual(len(lines), 5)
        self.assertIn("- category CURL, exerciseName CURL", lines)

    def test_a_count_that_differs_lists_every_step_after_the_ones_that_pair_up(self) -> None:
        sent = lc.set_body(None)
        stored = json.loads(json.dumps(sent))
        extra = {"stepType": {"stepTypeKey": "interval"}, "exerciseName": "EXTRA", "category": None}
        stored["workoutSegments"][0]["workoutSteps"].append(extra)
        lines = lc.compare(sent, stored)
        self.assertTrue(lines[4].startswith("The counts differed"))
        self.assertEqual(lines[-1], "- category None, exerciseName EXTRA")
        self.assertEqual(lc.compare(sent, json.loads(json.dumps(sent)))[-1][:4], "Set ")

    def test_set_steps_inside_a_repeat_group_are_read_and_rests_left_out(self) -> None:
        three = workout.Exercise("Check", "CURL", "CURL", (workout.Set(reps=10),) * 3, rest_seconds=60)
        body = workout.build(workout.Workout(workout.ROUTINE, "check", "Check", (three,)), None)
        self.assertEqual(body["workoutSegments"][0]["workoutSteps"][0]["type"], "RepeatGroupDTO")
        self.assertEqual([step["exerciseName"] for step in lc.sets(body)], ["CURL"])

    def test_it_saves_and_prints_every_shape_and_the_two_trainer_indexes(self) -> None:
        _, out = self.record()
        saved = self.saved()
        self.assertEqual(
            sorted(saved["hevy"]), ["exercise_history", "folders", "routines", "template", "workout_events"]
        )
        self.assertEqual(
            sorted(saved["hevy_trainer"]),
            [
                "exercise_template_units",
                "program",
                "trainer_preferences",
                "user_key_values",
                "user_preferences",
                "user_workouts_paged",
            ],
        )
        self.assertEqual(
            sorted(saved["garmin"]),
            [
                "calendar",
                "schedule_reply",
                "sent_to_the_watch",
                "sets",
                "settings",
                "step_cap",
                "stored_steps",
                "stored_workout",
                "workout_list_item",
            ],
        )
        self.assertEqual(saved["hevy_trainer_order"], {"next_workout_index": 1, "template_index_values": [0, 1]})
        folder = {"created_at": "str", "id": "int", "index": "int", "title": "str", "updated_at": "str"}
        self.assertEqual(saved["hevy"]["folders"], [folder])
        self.assertEqual(saved["hevy_trainer"]["exercise_template_units"], {"<key>": {"unit": "str"}})
        self.assertIn(json.dumps(saved, indent=1, sort_keys=True), out)

    def test_no_value_reaches_the_output_or_the_saved_file(self) -> None:
        _, out = self.record()
        written = "\n".join(p.read_text(encoding="utf-8") for p in self.folder.iterdir() if p.name != garmin.TOKENS)
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, out)
                self.assertNotIn(secret, written)

    def test_it_never_writes_to_hevy_and_keeps_no_hevy_session(self) -> None:
        self.record()
        self.assertEqual([p for p, _ in self.private_api.requests if p == "auth/refresh_token"], [])
        self.assertTrue(all(not hasattr(self.hevy_api, verb) for verb in ("post", "put", "delete")))
        self.assertEqual(
            sorted(p.name for p in self.folder.iterdir()),
            [lc.CREATED, garmin.TOKENS, f"{garmin.TOKENS}.seed", lc.RECORDED],
        )

    def test_the_garmin_token_is_its_own_sign_in_kept_only_in_the_folder(self) -> None:
        self.record()
        self.assertEqual(self.tokens, [TOKEN])
        self.assertEqual(self.store.read(garmin.TOKENS), fixtures.GARMIN_TOKENS)

    def test_with_nothing_set_it_asks_for_the_key_and_the_cookie_and_an_empty_one_skips_trainer(self) -> None:
        self.hevy_api.routines = []
        self.answers = [API_KEY, ""]
        code, _ = self.record(env={})
        self.assertEqual(code, 0)
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(self.hevy_api.headers[0]["api-key"], API_KEY)
        self.assertEqual(self.private_api.requests, [])
        self.assertEqual(sorted(self.saved()["hevy"]), ["folders", "routines", "workout_events"])
        self.assertNotIn("hevy_trainer", self.saved())

    def test_an_account_with_no_program_still_records_the_rest(self) -> None:
        self.private_api.program = None
        self.record()
        self.assertEqual(
            self.saved()["hevy_trainer_order"], {"next_workout_index": "NoneType", "template_index_values": []}
        )

    def test_an_index_that_is_not_a_whole_number_shows_as_its_type(self) -> None:
        self.assertEqual([lc.index_value(v) for v in (2, True, "1", None)], [2, "bool", "str", "NoneType"])

    def test_a_profile_without_a_usable_zone_puts_them_on_todays_utc_date(self) -> None:
        for zone in (None, "Not/AZone"):
            with self.subTest(zone=zone):
                self.setUp()
                self.garmin_api.zone = zone
                self.assertEqual(self.record()[0], 0)
                days = {e["calendarDate"] for e in self.garmin_api.entries.values()}
                self.assertEqual(days, {fixtures.NOW.astimezone(UTC).date().isoformat()})

    def test_a_watch_that_takes_none_is_noted_and_the_run_goes_on(self) -> None:
        self.garmin_api.fail("push_workout_to_device", fixtures.garmin_error(400))
        code, out = self.record()
        self.assertEqual(code, 0)
        self.assertIs(self.saved()["garmin"]["sent_to_the_watch"], False)
        self.assertEqual(self.saved()["garmin"]["step_cap"], ["250 steps: accepted"])
        self.assertIn(f"{lc.SET_WORKOUT} is on today's calendar but was not sent to a watch", out)

    def test_an_earlier_run_not_cleaned_up_stops_it_before_any_call(self) -> None:
        self.store.write(lc.CREATED, json.dumps({"workouts": [1]}))
        code, out = self.record()
        self.assertEqual(code, 1)
        self.assertIn("run `make live-cleanup` first", out)
        self.assertEqual((self.hevy_api.requests, self.garmin_api.calls), ([], []))

    def test_hevy_failing_stops_it_before_the_garmin_sign_in(self) -> None:
        signed_in: list[bool] = []

        def sign_in() -> str:
            signed_in.append(True)
            return TOKEN

        self.hevy_api.fail(503)
        code, out = self.record(sign_in=sign_in)
        self.assertEqual(code, 1)
        self.assertIn("Reading Hevy failed (Unavailable). Nothing was made in Garmin.", out)
        self.assertEqual(signed_in, [])

    def test_a_cookie_that_is_not_one_says_so(self) -> None:
        code, out = self.record(env={"HEVY_API_KEY": API_KEY, "HEVY_SESSION": "not-it"})
        self.assertEqual(code, 1)
        self.assertIn("HEVY_SESSION is not the auth2.0-token cookie", out)
        self.assertNotIn("not-it", out)

    def test_a_refused_sign_in_makes_nothing(self) -> None:
        def refused() -> str:
            raise garminconnect.GarminConnectTooManyRequestsError("Too many login attempts.")

        code, out = self.record(sign_in=refused)
        self.assertEqual(code, 1)
        self.assertIn("The Garmin sign-in failed (GarminConnectTooManyRequestsError)", out)
        self.assertEqual(self.garmin_api.workouts, {})
        self.assertIn("hevy", self.saved())

    def test_a_garmin_failure_partway_names_what_was_made_and_leaves_its_ids(self) -> None:
        self.garmin_api.fail("schedule_workout", fixtures.garmin_error(500))
        code, out = self.record()
        self.assertEqual(code, 1)
        self.assertIn("Garmin failed partway (Unavailable). 1 check workouts are left in Garmin", out)
        self.assertEqual(self.created(), list(self.garmin_api.workouts))

    def test_with_a_cookie_the_units_reply_is_recorded_in_either_form_trainer_reads(self) -> None:
        # The two forms `trainer._units` reads: a list of rows, and a dict holding one. Each row's fields show.
        row = {"exercise_template_id": "T-BENCH", "weight_unit": "kg"}
        fields = {"exercise_template_id": "str", "weight_unit": "str"}
        for reply, recorded in (([row], [fields]), ({"units": [row]}, {"units": [fields]})):
            with self.subTest(reply=reply):
                self.setUp()
                self.private_api.units = reply
                self.assertEqual(trainer._units(reply), {"T-BENCH": "kg"})
                self.record()
                self.assertEqual(self.saved()["hevy_trainer"]["exercise_template_units"], recorded)


class RecordHevyTest(LiveCheckCase):
    def saved_hevy(self) -> dict[str, Any]:
        recorded: dict[str, Any] = json.loads(self.store.read(lc.HEVY_RECORDED) or "{}")
        return recorded

    def test_with_no_routines_the_template_comes_from_a_logged_workout(self) -> None:
        self.hevy_api.routines = []
        self.hevy_api.events = [fixtures.hevy_workout_event("w-1", "T-BENCH", "Bench Press")]
        code, out = self.record_hevy()
        self.assertEqual(code, 0)
        saved = self.saved_hevy()
        self.assertEqual(
            sorted(saved["hevy"]), ["exercise_history", "folders", "routines", "template", "workout_events"]
        )
        self.assertEqual(saved["hevy"]["routines"], [])
        self.assertIn("hevy_trainer", saved)
        self.assertIn(f"Saved to live-check/{lc.HEVY_RECORDED}", out)
        self.assertIn(json.dumps(saved, indent=1, sort_keys=True), out)

    def test_it_writes_its_own_file_makes_nothing_and_an_earlier_run_does_not_hold_it_back(self) -> None:
        self.store.write(lc.RECORDED, "from record\n")
        self.store.write(lc.CREATED, json.dumps({"workouts": [1]}))
        code, _ = self.record_hevy()
        self.assertEqual(code, 0)
        self.assertEqual(self.store.read(lc.RECORDED), "from record\n")
        self.assertEqual(json.loads(self.store.read(lc.CREATED) or "{}"), {"workouts": [1]})
        self.assertEqual(self.garmin_api.calls, [])
        self.assertEqual(self.tokens, [])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [lc.CREATED, lc.HEVY_RECORDED, lc.RECORDED])

    def test_enter_at_the_cookie_prompt_reads_hevy_alone(self) -> None:
        self.answers = [""]
        code, _ = self.record_hevy(env={"HEVY_API_KEY": API_KEY})
        self.assertEqual(code, 0)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.private_api.requests, [])
        self.assertNotIn("hevy_trainer", self.saved_hevy())

    def test_a_failed_read_saves_nothing(self) -> None:
        self.hevy_api.fail(503)
        code, out = self.record_hevy()
        self.assertEqual(code, 1)
        self.assertIn("Reading Hevy failed (Unavailable).", out)
        self.assertIsNone(self.store.read(lc.HEVY_RECORDED))

    def test_no_value_reaches_the_output_or_the_saved_file(self) -> None:
        self.hevy_api.events = [fixtures.hevy_workout_event("w-1", "T-BENCH", "Bench Press")]
        _, out = self.record_hevy()
        written = self.store.read(lc.HEVY_RECORDED) or ""
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, out)
                self.assertNotIn(secret, written)


class TrainerEditsTest(LiveCheckCase):
    def test_each_edit_says_whether_it_is_already_in_its_template_and_nothing_personal_shows(self) -> None:
        applied = {"type": "swap", "from_exercise_template_id": "T-OLD", "to_exercise_template_id": "T-GOBLET"}
        pending = {"type": "swap", "from_exercise_template_id": "T-LUNGE", "to_exercise_template_id": "T-NEW"}
        exercises = [trainer_exercise("T-GOBLET"), trainer_exercise("T-LUNGE")]
        lower = trainer_template("t-lower", "lower_2x_a", exercises, edits=[applied, pending])
        upper = trainer_template("t-upper", "upper_2x_a", [trainer_exercise("T-SIDE-BEND")])
        updated = (fixtures.NOW - timedelta(minutes=12, seconds=30)).astimezone(UTC).isoformat()
        program = trainer_program([upper, lower], updated_at=updated)
        program["templates"].reverse()  # the reply's order is not `index` order
        self.private_api.program = program
        code, out = self.record_hevy()
        self.assertEqual(code, 0)
        saved = json.loads(self.store.read(lc.HEVY_RECORDED) or "{}")
        self.assertEqual(
            saved["hevy_trainer_edits"],
            {
                "program_updated_minutes_ago": 12,
                "templates": [
                    {"exercise_count": 1, "edits": []},
                    {
                        "exercise_count": 2,
                        "edits": [
                            {"type": "swap", "from_in_exercises": False, "to_in_exercises": True},
                            {"type": "swap", "from_in_exercises": True, "to_in_exercises": False},
                        ],
                    },
                ],
            },
        )
        self.assertIn(
            "Hevy Trainer edits, per template in index order (is each edit already in its exercises?):\n"
            "Program updated 12 minutes ago\n"
            "Template 1 (1 exercises): no edits\n"
            "Template 2 (2 exercises): swap, from in exercises False, to in exercises True\n"
            "Template 2 (2 exercises): swap, from in exercises True, to in exercises False\n",
            out,
        )
        written = self.store.read(lc.HEVY_RECORDED) or ""
        for secret in ("T-OLD", "T-NEW", "T-GOBLET", "T-LUNGE", "t-lower", updated[:10]):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, out)
                self.assertNotIn(secret, written)

    def test_an_odd_edit_type_shows_as_its_type_and_a_missing_date_says_so(self) -> None:
        program = {"templates": [{"edits": [{"type": "Swap-1"}, {"type": None}]}]}
        found = lc.trainer_edits(program, fixtures.NOW)
        self.assertEqual(found["program_updated_minutes_ago"], "NoneType")
        self.assertEqual([e["type"] for e in found["templates"][0]["edits"]], ["str", "NoneType"])
        self.assertEqual(found["templates"][0]["exercise_count"], 0)
        self.assertEqual(lc.edit_lines(lc.trainer_edits(None, fixtures.NOW)), ["Program's updated_at: NoneType"])

    def test_the_full_run_prints_them_too_and_without_a_cookie_there_are_none(self) -> None:
        _, out = self.record()
        self.assertIn("Hevy Trainer edits, per template in index order", out)
        self.assertIn("hevy_trainer_edits", self.saved())
        self.answers = [""]
        _, out = self.record_hevy(env={"HEVY_API_KEY": API_KEY})
        self.assertNotIn("Hevy Trainer edits", out)


class KeyValueStoreTest(LiveCheckCase):
    """`user_key_values`, read to find where Hevy keeps a swap made for one workout only."""

    HEADING = "Hevy user_key_values, where a one-off swap may be kept (key names, types and shapes, no values):\n"
    SWAPPED_IN = "T-BOGLE"  # the form of the program's exercise ids, and not one of them
    VALUES = ("dark", SWAPPED_IN, "t-lower", "T-LUNGE", "T-GOBLET", "someone", "from-me")

    def setUp(self) -> None:
        super().setUp()
        lower = trainer_template("t-lower", "lower_2x_a", [trainer_exercise("T-GOBLET"), trainer_exercise("T-LUNGE")])
        self.private_api.program = trainer_program([lower])

    def run_hevy(self) -> tuple[str, dict[str, Any]]:
        code, out = self.record_hevy()
        self.assertEqual(code, 0)
        saved: dict[str, Any] = json.loads(self.store.read(lc.HEVY_RECORDED) or "{}")
        return out, saved

    def assert_no_value(self, out: str) -> None:
        written = self.store.read(lc.HEVY_RECORDED) or ""
        for value in self.VALUES:
            with self.subTest(value=value):
                self.assertNotIn(value, out)
                self.assertNotIn(value, written)

    def test_a_dict_of_keys_lists_each_name_type_and_json_shape_and_finds_a_swapped_in_id(self) -> None:
        self.private_api.key_values = {
            "trainer_one_off_swaps": json.dumps({"t-lower": {"from": "T-LUNGE", "to": self.SWAPPED_IN}}),
            "theme": "dark",
            "workout_count": 5,
            f"swap_{self.SWAPPED_IN}": None,
            "prefs_someone": "from-me",
            "someone@example.com": "1",
        }
        out, saved = self.run_hevy()
        lines = [
            "Hevy sent a dict of keys, 6 entries:",
            '- trainer_one_off_swaps: str, JSON {"<key>": {"from": "str", "to": "str"}}; a template id True, '
            "a program exercise id True, an exercise id not in the program True",
            "- theme: str",
            "- workout_count: int; a template id False, a program exercise id False, an exercise id not in the "
            "program False",
            "- swap_<id>: NoneType; a template id False, a program exercise id False, an exercise id not in the "
            "program True",
            "- prefs_<id>: str",
            '- <key>: str, JSON "int"',
        ]
        self.assertIn(self.HEADING + "\n".join(lines) + "\n", out)
        self.assertEqual(saved["hevy_trainer_key_values"]["form"], "a dict of keys")
        self.assertEqual(saved["hevy_trainer"]["user_key_values"]["theme"], "str")
        self.assert_no_value(out)

    def test_a_list_of_rows_is_read_by_its_key_and_value(self) -> None:
        self.private_api.key_values = [{"key": "trainer_swap", "value": self.SWAPPED_IN}, "loose"]
        out, saved = self.run_hevy()
        self.assertIn(
            self.HEADING + "Hevy sent a list of rows, 2 entries:\n- trainer_swap: str; a template id False, a program "
            "exercise id False, an exercise id not in the program True\n- <key>: str\n",
            out,
        )
        self.assertEqual(saved["hevy_trainer"]["user_key_values"], [{"key": "str", "value": "str"}])
        self.assert_no_value(out)

    def test_a_long_store_lists_sixty_and_counts_the_rest(self) -> None:
        self.private_api.key_values = {f"key_{n}": n for n in range(65)}
        out, saved = self.run_hevy()
        self.assertIn("Hevy sent a dict of keys, 65 entries:\n", out)
        self.assertIn("- key_59: int\nand 5 more\n", out)
        self.assertEqual(len(saved["hevy_trainer_key_values"]["entries"]), 60)

    def test_another_kind_of_reply_says_what_it_was(self) -> None:
        self.private_api.key_values = "made up"
        out, _ = self.run_hevy()
        self.assertIn(self.HEADING + "Hevy sent str, 0 entries:\n", out)
        self.assertEqual(lc.ProgramIds.of(None).look_alikes(self.SWAPPED_IN), [])
        self.assertEqual(list(lc._strings(["a", {"b": 1}, '["c"]'])), ["a", "b", '["c"]', "c"])

    def test_a_refusal_is_recorded_and_the_run_goes_on(self) -> None:
        for reply, said in (
            (fixtures.FakeResponse(404, {"error": "made up"}), "refused (NotFound, HTTP 404)"),
            (fixtures.FakeResponse(503, "from-me"), "refused (Unavailable, HTTP 503)"),
        ):
            with self.subTest(said=said):
                self.setUp()
                self.private_api.key_values = reply
                out, saved = self.run_hevy()
                self.assertIn(self.HEADING + said + "\n", out)
                self.assertEqual(saved["hevy_trainer"]["user_key_values"], said)
                self.assertIn("program", saved["hevy_trainer"])
                self.assert_no_value(out)

    def test_a_failure_with_no_status_says_none(self) -> None:
        self.private_api.fail(None, None, None, None, None, requests.ConnectionError("from-me"))
        out, saved = self.run_hevy()
        self.assertEqual(saved["hevy_trainer"]["user_key_values"], "refused (Unavailable, HTTP none)")
        self.assertNotIn("from-me", out)


class CleanupTest(LiveCheckCase):
    def test_it_removes_only_its_workouts_and_entries_then_the_token(self) -> None:
        self.garmin_api.workouts[1] = {"workoutId": 1, "workoutName": lc.SET_WORKOUT, "description": "someone else's"}
        self.garmin_api.workouts[2] = {"workoutId": 2, "workoutName": "Hevy: Push", "description": workout.FIRST_LINE}
        self.garmin_api.schedule_workout(2, fixtures.TODAY.isoformat())
        self.record()
        code, out = self.cleanup()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), sorted([lc.SET_WORKOUT, "Hevy: Push"]))
        self.assertEqual(list(self.garmin_api.workouts)[0], 1)
        self.assertEqual([e["workout"]["workoutId"] for e in self.garmin_api.entries.values()], [2])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [lc.RECORDED])
        self.assertIn("Removed 1 calendar entries and 1 check workouts", out)

    def test_it_removes_a_step_probe_a_failed_run_left(self) -> None:
        self.garmin_api.fail("delete_workout", fixtures.garmin_error(500))
        self.record()
        code, out = self.cleanup()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), [])
        self.assertIn("Removed 1 calendar entries and 2 check workouts", out)

    def test_a_second_run_has_nothing_to_do(self) -> None:
        self.record()
        self.cleanup()
        self.assertEqual(self.cleanup(), (0, "Nothing to clean up.\n"))

    def test_with_no_id_file_it_goes_by_the_two_names_alone(self) -> None:
        self.garmin_api.fail("upload_workout", fixtures.garmin_error(500))
        self.record()
        self.store.remove(lc.CREATED)
        self.garmin_api.workouts[1] = {"workoutId": 1, "workoutName": lc.STEPS_WORKOUT}
        self.garmin_api.workouts[2] = {"workoutId": 2, "workoutName": "HGS check 7"}
        code, out = self.cleanup()
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), ["HGS check 7"])
        self.assertIn("Removed 0 calendar entries and 1 check workouts", out)

    def test_an_id_file_without_the_token_says_to_delete_by_hand(self) -> None:
        self.store.write(lc.CREATED, json.dumps({"workouts": [1]}))
        code, out = self.cleanup()
        self.assertEqual(code, 1)
        self.assertIn("Delete the workouts named `HGS check ...` in Garmin Connect by hand", out)

    def test_a_garmin_failure_keeps_the_token_and_the_ids_for_another_try(self) -> None:
        self.record()
        self.garmin_api.fail("get_workouts", fixtures.garmin_error(500))
        code, out = self.cleanup()
        self.assertEqual(code, 1)
        self.assertIn("Cleanup failed (Unavailable). Run `make live-cleanup` again.", out)
        self.assertIsNotNone(self.store.read(lc.CREATED))
        self.assertIsNotNone(self.store.read(garmin.TOKENS))


class ShapeTest(unittest.TestCase):
    def test_keys_that_could_be_values_are_hidden_and_field_names_kept(self) -> None:
        reply = {
            "workoutId": 1,
            "userData": {"timeZone": "America/Los_Angeles"},
            "2026-01-15": [{"exercise_template_id": "T-BENCH"}],
            "D04AC939": "kg",
            "someone@example.com": None,
        }
        self.assertEqual(
            lc.shape(reply),
            {"workoutId": "int", "userData": {"timeZone": "str"}, "<key>": "NoneType"},
        )


class MainTest(unittest.TestCase):
    def test_each_command_runs_its_function_on_the_folder_in_the_repo(self) -> None:
        for command, function in (("record", "record"), ("record-hevy", "record_hevy"), ("cleanup", "cleanup")):
            with self.subTest(command=command), mock.patch.object(lc, function, return_value=0) as run:
                self.assertEqual(lc.main([command], env={}, out=io.StringIO()), 0)
                self.assertEqual(run.call_args.args[-2], lc.FOLDER)
        self.assertEqual(lc.FOLDER, Path(lc.__file__).resolve().parents[1] / "live-check")


if __name__ == "__main__":
    unittest.main()
