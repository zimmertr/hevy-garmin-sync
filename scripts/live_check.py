"""One run by hand against TJ's own accounts, for #22, #24 and #6. CI never runs it.

`make live-check` runs `record`, and `make live-cleanup` runs `cleanup` once the watch has been
looked at. `make live-check-hevy` runs `record-hevy`. All run in Docker, from a clone, on TJ's
machine.

`record`:
1. Reads Hevy's public API with HEVY_API_KEY, and Hevy's private API when HEVY_SESSION is set
   (a fresh cookie from a private window, never the pod's), and keeps the shape of each reply.
   The exercise template and its history are read for the first exercise of a routine, else of
   a logged workout. For Hevy Trainer it also keeps `next_workout_index` and the templates'
   `index` values, which the calendar rule reads (spec F-31).
2. Signs in to Garmin as its own session (`login.sign_in`), then creates `HGS check names`, with
   one step for every exercise map row whose category Garmin stored differently on 2026-11-10
   (#22), and `HGS check 1` to `HGS check 6` (#6). It reads the first back and prints, step by
   step, the exercise sent and the one Garmin stored. Last it creates `HGS check step name`, one
   step with a `stepName` and no exercise (#24), on its own: Garmin may refuse such a step, and a
   refusal there is recorded without costing the other checks. Then it puts every workout it made,
   seven or eight, on today and sends them to the watch, as the app does.
3. Writes what it recorded to live-check/recorded.json and prints it, for the issues.

`cleanup` removes those workouts from the calendar and deletes them, then the saved Garmin token.
It is safe to run again.

`record-hevy` is step 1 alone, written to live-check/recorded-hevy.json: no Garmin sign-in,
nothing made anywhere, and not held back by an earlier run that wasn't cleaned up.

Safety, enforced in code:
- Never writes to Hevy: only the read methods of `Hevy` and `HevyPrivate` are called.
- Deletes and unschedules only its own workouts: a Garmin workout that carries one of the eight
  names and, when live-check/created.json is there, one of the ids it lists. The workouts'
  description is not the app's (`workout.owner` gives None), so the running app never claims or
  deletes them.
- Prints and saves shapes, never a value: `shape` keeps keys and type names, and replaces any key
  that could itself be a value, such as an id or a date, with `<key>`. The only values out are
  Garmin's exercise keys, the invented step name, and the two Trainer index values above. Errors
  print their type only.
- Never reads a token or session from DATA_DIR or a cluster. The Garmin token is the one its own
  sign-in returned, kept only in live-check/ (git and Docker builds ignore it), never printed, and
  removed by `cleanup`. The Hevy session lives in a temporary folder that is gone when `record`
  ends.
"""

import argparse
import getpass
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import garminconnect
import requests

from hevy_garmin_sync import exercises, login, trainer, workout
from hevy_garmin_sync.errors import ConfigError, Refused, ServiceError
from hevy_garmin_sync.garmin import TOKENS, Garmin
from hevy_garmin_sync.hevy import Hevy
from hevy_garmin_sync.hevy_private import _WORKOUT_PAGE, HevyPrivate, parse_cookie
from hevy_garmin_sync.store import Store
from hevy_garmin_sync.workout import Exercise, Set, Workout

FOLDER = Path(__file__).resolve().parents[1] / "live-check"
RECORDED = "recorded.json"
HEVY_RECORDED = "recorded-hevy.json"  # `record-hevy`'s, so it never overwrites what `record` saved
CREATED = "created.json"
NAMES_WORKOUT = "HGS check names"
CALENDAR_WORKOUTS = tuple(f"HGS check {n}" for n in range(1, 7))
STEP_NAME_WORKOUT = "HGS check step name"
NAMES = (NAMES_WORKOUT, *CALENDAR_WORKOUTS, STEP_NAME_WORKOUT)
# Not the app's first line, so `workout.owner` never takes one of these for the app's (F-12).
DESCRIPTION = "Made by hevy-garmin-sync's scripts/live_check.py; `make live-cleanup` deletes it."
CHECKED_CATEGORIES = ("BATTLE_ROPE", "HYPEREXTENSION")  # stored as another exercise on 2026-11-10 (#22)
STEP_NAME = "HGS Check Step Name"  # invented, so the watch shows whether it reads `stepName` (#24)
STEP_NAME_CATEGORY = "CORE"  # hevy2garmin kept the category beside its `stepName`
CALENDAR_EXERCISE = Exercise("Check", "CURL", "CURL", (Set(reps=10),))
CALENDAR_DAYS = 31  # how far either side of today `cleanup` looks for the check workouts' entries
_KEY = re.compile(r"[a-z][A-Za-z_]*")  # a key that names a field; anything else may be a value

Json = dict[str, Any]


class CheckGarmin(Garmin):
    """The app's Garmin, plus three replies the app reads only in part, kept whole for their shapes."""

    def settings(self) -> Json:
        return self._call(self._api.get_user_profile)

    def stored(self, workout_id: int) -> Json:
        return self._call(lambda: self._api.get_workout_by_id(workout_id))

    def schedule_reply(self, workout_id: int, day: date) -> Any:
        return self._call(lambda: self._api.schedule_workout(workout_id, day.isoformat()), write=True)


OpenGarmin = Callable[[str | None, Store], CheckGarmin]


def shape(value: Any) -> Any:
    """`trainer.shape`, with every key that could be a value, such as an id or a date, made `<key>`."""

    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            return {(key if _KEY.fullmatch(key) else "<key>"): scrub(item) for key, item in node.items()}
        if isinstance(node, list):
            return [scrub(item) for item in node]
        return node

    return scrub(trainer.shape(value))


def index_value(value: Any) -> int | str:
    """A Trainer index as it is, or its type's name when it isn't a whole number."""
    return value if isinstance(value, int) and not isinstance(value, bool) else type(value).__name__


def read_hevy(hevy: Hevy, now: datetime) -> Json:
    folders = hevy.folders()
    routines = hevy.routines()
    events = hevy.workout_events(now - timedelta(days=30))
    shapes: Json = {"folders": shape(folders), "routines": shape(routines), "workout_events": shape(events)}
    # A routine's exercise, else a logged workout's, so an account with no routines still records both.
    lists = [r.get("exercises") for r in routines] + [(e.get("workout") or {}).get("exercises") for e in events]
    template_ids = [
        str(e["exercise_template_id"]) for listed in lists for e in listed or [] if e.get("exercise_template_id")
    ]
    if template_ids:
        shapes["template"] = shape(hevy.template(template_ids[0]))
        shapes["exercise_history"] = shape(hevy.exercise_history(template_ids[0], now - timedelta(days=365), now))
    return shapes


def read_trainer(private: HevyPrivate) -> tuple[Json, Json]:
    """The shapes of the private replies, and the two index values the calendar rule reads."""
    user = private.user_preferences()
    program = private.program()
    shapes: Json = {
        "user_preferences": shape(user),
        "trainer_preferences": shape(private.trainer_preferences()),
        "exercise_template_units": shape(private.unit_overrides()),
        "program": shape(program),
        # The page as Hevy sends it, which `workouts_since` unpacks, at the one page size Hevy takes.
        "user_workouts_paged": shape(
            private._get(
                "user_workouts_paged",
                {"username": str(user.get("username") or ""), "limit": _WORKOUT_PAGE, "offset": 0},
            )
        ),
    }
    templates = (program or {}).get("templates") or []
    order: Json = {
        "next_workout_index": index_value((program or {}).get("next_workout_index")),
        "template_index_values": [index_value(t.get("index")) for t in templates],
    }
    return shapes, order


def checked_rows() -> list[tuple[str, str]]:
    """Every map row, of either table, in a category Garmin stored as another exercise (#22)."""
    found = []
    for table in ("exercise_map.csv", "custom_exercise_map.csv"):
        for row in exercises.rows(exercises.DATA / table):
            if row["garmin_category"] in CHECKED_CATEGORIES:
                found.append((row["garmin_category"], row["garmin_name"]))
    return found


def names_body(system: str | None) -> Json:
    steps = tuple(Exercise("Check", category, name, (Set(reps=10),)) for category, name in checked_rows())
    return workout.build(Workout(workout.ROUTINE, "check", NAMES_WORKOUT, steps), system) | {
        "description": DESCRIPTION
    }


def step_name_body(system: str | None) -> Json:
    """One step with a `stepName` and no exercise, as hevy2garmin sent for an exercise it couldn't match (#24)."""
    step = Exercise("Check", STEP_NAME_CATEGORY, STEP_NAME_CATEGORY, (Set(reps=10),))
    body = workout.build(Workout(workout.ROUTINE, "check", STEP_NAME_WORKOUT, (step,)), system)
    (only,) = sets(body)
    del only["exerciseName"]
    only["stepName"] = STEP_NAME
    return body | {"description": DESCRIPTION}


def calendar_body(name: str, system: str | None) -> Json:
    return workout.build(Workout(workout.ROUTINE, "check", name, (CALENDAR_EXERCISE,)), system) | {
        "description": DESCRIPTION
    }


def sets(body: Json) -> Iterator[Json]:
    """A workout's set steps in order, inside repeat groups too; rests left out."""

    def walk(steps: Sequence[Json]) -> Iterator[Json]:
        for step in steps:
            if step.get("workoutSteps"):
                yield from walk(step["workoutSteps"])
            elif (step.get("stepType") or {}).get("stepTypeKey") in ("interval", "warmup"):
                yield step

    for segment in body.get("workoutSegments") or []:
        yield from walk(segment.get("workoutSteps") or [])


def named_steps(node: Any) -> Iterator[Json]:
    """Every dict anywhere in a reply that has an `exerciseName` or a `stepName`, in order, whatever the nesting."""
    if isinstance(node, dict):
        if "exerciseName" in node or "stepName" in node:
            yield node
        for value in node.values():
            yield from named_steps(value)
    elif isinstance(node, list):
        for item in node:
            yield from named_steps(item)


def compare(sent: Json, stored: Json) -> list[str]:
    """One line per step: the exercise sent and the one Garmin stored. Garmin's keys only.

    Should Garmin nest the stored steps in another way, the step counts differ, and every step a
    plain walk finds is listed too, so the run still answers what Garmin stored (#22).
    """
    out_steps, back_steps = list(sets(sent)), list(sets(stored))
    lines = []
    for number, (out, back) in enumerate(zip(out_steps, back_steps, strict=False), start=1):
        stored_pair = f"{back.get('category')} / {back.get('exerciseName')}"
        if "stepName" in out:
            kept = "kept" if back.get("stepName") == STEP_NAME else "not kept"
            what = f"{out['category']} with a stepName and no exercise"
            lines.append(f"Step {number}: sent {what}, Garmin stored {stored_pair}, stepName {kept}")
        else:
            what = f"{out['category']} / {out['exerciseName']}"
            lines.append(f"Step {number}: sent {what}, Garmin stored {stored_pair}")
    if len(out_steps) != len(back_steps):
        lines.append(
            f"The counts differed: {len(out_steps)} steps sent, {len(back_steps)} found where the app reads them. "
            "Every step found anywhere in the stored workout:"
        )
        for found in named_steps(stored):
            lines.append(
                f"- category {found.get('category')}, exerciseName {found.get('exerciseName')}, "
                f"stepName {found.get('stepName')}"
            )
    return lines


def save(store: Store, name: str, value: Any) -> None:
    store.write(name, json.dumps(value, indent=1, sort_keys=True) + "\n")


def check_garmin(garmin: CheckGarmin, store: Store, created: list[int], utcnow: Callable[[], datetime]) -> Json:
    """Create, read back, schedule and send the check workouts. `created` gets each id as it is made."""
    try:
        zone = ZoneInfo(garmin.time_zone() or "UTC")  # "today" as the app works it out with TZ unset (C-7)
    except ZoneInfoNotFoundError, ValueError, OSError:
        zone = ZoneInfo("UTC")
    today = utcnow().astimezone(zone).date()
    system = garmin.measurement_system()
    recorded: Json = {"settings": shape(garmin.settings())}

    sent = names_body(system)
    for body in (sent, *(calendar_body(name, system) for name in CALENDAR_WORKOUTS)):
        created.append(garmin.create(body))
        save(store, CREATED, {"workouts": created})  # at once, so a failure later still leaves cleanup the id

    stored = garmin.stored(created[0])
    recorded["stored_workout"] = shape(stored)
    recorded["steps"] = compare(sent, stored)

    # Last and alone: Garmin may refuse a step with no exercise, and that must not cost the checks above.
    named = step_name_body(system)
    try:
        named_id = garmin.create(named)
    except Refused as e:
        recorded["step_name"] = [f"Garmin refused a step with a stepName and no exercise ({type(e).__name__})"]
    else:
        created.append(named_id)
        save(store, CREATED, {"workouts": created})
        recorded["step_name"] = compare(named, garmin.stored(named_id))

    for workout_id in created:
        recorded["schedule_reply"] = shape(garmin.schedule_reply(workout_id, today))
    unsent = 0
    for workout_id in created:
        try:
            garmin.send_to_device(workout_id)
        except Refused:
            unsent += 1  # no watch to send to; the calendar entry still stands (Sync._send)
    recorded["not_sent_to_the_watch"] = unsent

    listed = [w for w in garmin.workouts() if w.get("workoutId") == created[0]]
    recorded["workout_list_item"] = shape(listed[0] if listed else None)
    recorded["calendar"] = shape(garmin.scheduled(today, today))
    return recorded


def record(
    env: Mapping[str, str],
    folder: Path,
    out: TextIO,
    *,
    ask: Callable[[str], str] = getpass.getpass,
    sign_in: Callable[[], str] = login.sign_in,
    open_garmin: OpenGarmin = CheckGarmin.open,
    hevy_session: requests.Session | None = None,
    private_session: requests.Session | None = None,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    store = Store(folder)
    if store.read(CREATED) is not None:
        print("live-check/created.json is from an earlier run: run `make live-cleanup` first.", file=out)
        return 1
    recorded = read_all_hevy(env, out, ask, hevy_session, private_session, utcnow)
    if recorded is None:
        return 1
    save(store, RECORDED, recorded)

    try:
        token = sign_in()
    except (
        garminconnect.GarminConnectTooManyRequestsError,
        garminconnect.GarminConnectAuthenticationError,
        garminconnect.GarminConnectConnectionError,
    ) as e:
        print(
            f"The Garmin sign-in failed ({type(e).__name__}). Hevy's shapes are saved; nothing was made in Garmin.",
            file=out,
        )
        return 1
    created: list[int] = []
    try:
        recorded["garmin"] = check_garmin(open_garmin(token, store), store, created, utcnow)
    except (ServiceError, ConfigError) as e:
        print(
            f"Garmin failed partway ({type(e).__name__}). {len(created)} of {len(NAMES)} check workouts were made; "
            "run `make live-cleanup` to delete them and the saved Garmin token.",
            file=out,
        )
        return 1
    save(store, RECORDED, recorded)

    print(f"{NAMES_WORKOUT}:", file=out)
    for line in recorded["garmin"]["steps"]:
        print(line, file=out)
    print(f"{STEP_NAME_WORKOUT}:", file=out)
    for line in recorded["garmin"]["step_name"]:
        print(line, file=out)
    print(f"\nSaved to live-check/{RECORDED}, which holds no values. Paste it into #22:\n", file=out)
    print(json.dumps(recorded, indent=1, sort_keys=True), file=out)
    print(
        f"\nThe {len(created)} check workouts are on today's calendar and on their way to the watch. Look at the "
        "watch, then run `make live-cleanup`.",
        file=out,
    )
    return 0


def read_all_hevy(
    env: Mapping[str, str],
    out: TextIO,
    ask: Callable[[str], str],
    hevy_session: requests.Session | None,
    private_session: requests.Session | None,
    utcnow: Callable[[], datetime],
) -> Json | None:
    """Hevy's shapes, and Hevy Trainer's when a cookie is given; None, said why, when a read fails."""
    # Asked for, not put on the command line, so neither lands in the shell's history.
    api_key = env.get("HEVY_API_KEY", "").strip() or ask("Hevy API key (not shown): ").strip()
    cookie = env.get("HEVY_SESSION", "").strip() or ask(
        "Hevy auth2.0-token cookie from a private window, or Enter to skip Hevy Trainer (not shown): "
    ).strip()
    recorded: Json = {}
    try:
        recorded["hevy"] = read_hevy(Hevy(api_key, hevy_session), utcnow())
        if cookie:
            with tempfile.TemporaryDirectory() as scratch:
                private = HevyPrivate(parse_cookie(cookie), Store(Path(scratch)), private_session)
                recorded["hevy_trainer"], recorded["hevy_trainer_order"] = read_trainer(private)
    except ConfigError as e:
        print(f"{e}. Nothing was made in Garmin.", file=out)  # the app's own words, which hold no value
        return None
    except ServiceError as e:
        print(f"Reading Hevy failed ({type(e).__name__}). Nothing was made in Garmin.", file=out)
        return None
    return recorded


def record_hevy(
    env: Mapping[str, str],
    folder: Path,
    out: TextIO,
    *,
    ask: Callable[[str], str] = getpass.getpass,
    hevy_session: requests.Session | None = None,
    private_session: requests.Session | None = None,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Hevy's reads alone, into a file of their own: no Garmin sign-in, nothing made anywhere."""
    recorded = read_all_hevy(env, out, ask, hevy_session, private_session, utcnow)
    if recorded is None:
        return 1
    save(Store(folder), HEVY_RECORDED, recorded)
    print(f"Saved to live-check/{HEVY_RECORDED}, which holds no values. Paste it into #22:\n", file=out)
    print(json.dumps(recorded, indent=1, sort_keys=True), file=out)
    return 0


def cleanup(
    folder: Path,
    out: TextIO,
    *,
    open_garmin: OpenGarmin = CheckGarmin.open,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    store = Store(folder)
    saved = store.read(CREATED)
    if store.read(TOKENS) is None:
        if saved is None:
            print("Nothing to clean up.", file=out)
            return 0
        print(
            "live-check/created.json lists check workouts, but the saved Garmin token is gone. Delete the "
            "workouts named `HGS check ...` in Garmin Connect by hand, then live-check/created.json.",
            file=out,
        )
        return 1
    ids = set(json.loads(saved)["workouts"]) if saved else None
    try:
        garmin = open_garmin(None, store)
        mine = {
            int(w["workoutId"])
            for w in garmin.workouts()
            if w.get("workoutName") in NAMES and (ids is None or w.get("workoutId") in ids)
        }
        today = utcnow().date()
        entries = [
            int(e["workoutScheduleId"])
            for e in garmin.scheduled(today - timedelta(days=CALENDAR_DAYS), today + timedelta(days=CALENDAR_DAYS))
            if (e.get("workout") or {}).get("workoutId") in mine and e.get("workoutScheduleId") is not None
        ]
        for entry_id in entries:
            garmin.unschedule(entry_id)
        for workout_id in sorted(mine):
            garmin.delete(workout_id)
    except (ServiceError, ConfigError) as e:
        print(f"Cleanup failed ({type(e).__name__}). Run `make live-cleanup` again.", file=out)
        return 1
    for name in (CREATED, TOKENS, f"{TOKENS}.seed"):
        store.remove(name)
    print(f"Removed {len(entries)} calendar entries and {len(mine)} check workouts, and the saved token.", file=out)
    return 0


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] = os.environ, out: TextIO = sys.stdout
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("record", "record-hevy", "cleanup"))
    args = parser.parse_args(argv)
    if args.command == "record":
        return record(env, FOLDER, out)
    if args.command == "record-hevy":
        return record_hevy(env, FOLDER, out)
    return cleanup(FOLDER, out)


if __name__ == "__main__":  # pragma: no cover (the tests call main(); this line only runs from a shell)
    raise SystemExit(main())
