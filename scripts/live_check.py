"""One run by hand against TJ's own accounts, for the open points in docs/DATA.md. CI never runs it.

`make live-check` runs `record`, and `make live-cleanup` runs `cleanup` once the watch has been
looked at. `make live-check-hevy` runs `record-hevy`. All run in Docker, from a clone, on TJ's
machine.

`record`:
1. Reads Hevy's public API with HEVY_API_KEY, and Hevy's private API when HEVY_SESSION is set
   (a fresh cookie from a private window, never the pod's), and keeps the shape of each reply.
   The exercise template and its history are read for the first exercise of a routine, else of
   a logged workout. For Hevy Trainer it also keeps `next_workout_index` and the templates'
   `index` values, which the calendar rule reads (spec F-31).
2. Signs in to Garmin as its own session (`login.sign_in`), then creates `HGS check set`: one set
   of `HYPEREXTENSION` / `HYPEREXTENSION` for 10 reps, a pair Garmin stores with an empty exercise
   name, then three matching sets that become a repeat group, then a two-round superset that
   becomes another. It reads it back, keeps the shape of each kind of step it finds, groups and the
   steps inside them included, prints the exercise sent and the one Garmin stored for each set,
   then puts it on today and sends it to the watch, as the app does. TJ records the first set on the
   watch, to see what Garmin Connect and Strava call it and which rep count they keep.
3. Probes Garmin's step cap: creates `HGS check steps` with about 250 steps that no repeat group
   can shorten, and deletes it at once, never scheduled or sent. If Garmin refuses it, it prints
   Garmin's status and reason, then tries about 100 steps, then about 50, and stops at the first
   size Garmin takes.
4. Writes what it recorded to live-check/recorded.json and prints it.

`cleanup` removes those workouts from the calendar and deletes them, then the saved Garmin token.
It is safe to run again.

`record-hevy` is step 1 alone, written to live-check/recorded-hevy.json: no Garmin sign-in,
nothing made anywhere, and not held back by an earlier run that wasn't cleaned up.

Safety, enforced in code:
- Never writes to Hevy: only the read methods of `Hevy` and `HevyPrivate` are called.
- Deletes and unschedules only its own workouts: a Garmin workout that carries one of the two
  names and, when live-check/created.json is there, one of the ids it lists. Each id is saved there
  the moment the workout exists. The workouts' description is not the app's (`workout.owner` gives
  None), so the running app never claims or deletes them.
- Prints and saves shapes, never a value: `shape` keeps keys and type names, and replaces any key
  that could itself be a value, such as an id or a date, with `<key>`. The only values out are
  Garmin's exercise and step type keys, the step counts tried, and the two Trainer index values
  above. Errors print their type only, but for Garmin refusing the step probe: there the status and
  Garmin's own reason are the answer, and they hold no personal data.
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

from hevy_garmin_sync import login, trainer, workout
from hevy_garmin_sync.errors import ConfigError, Refused, ServiceError, Unavailable
from hevy_garmin_sync.garmin import TOKENS, Garmin
from hevy_garmin_sync.hevy import Hevy
from hevy_garmin_sync.hevy_private import _WORKOUT_PAGE, HevyPrivate, parse_cookie
from hevy_garmin_sync.store import Store
from hevy_garmin_sync.workout import Exercise, Set, Workout

FOLDER = Path(__file__).resolve().parents[1] / "live-check"
RECORDED = "recorded.json"
HEVY_RECORDED = "recorded-hevy.json"  # `record-hevy`'s, so it never overwrites what `record` saved
CREATED = "created.json"
SET_WORKOUT = "HGS check set"
STEPS_WORKOUT = "HGS check steps"
NAMES = (SET_WORKOUT, STEPS_WORKOUT)
# Not the app's first line, so `workout.owner` never takes one of these for the app's (F-12).
DESCRIPTION = "Made by hevy-garmin-sync's scripts/live_check.py; `make live-cleanup` deletes it."
_TEN = Set(reps=10)
SET_EXERCISES = (
    # Garmin stored this pair with an empty exercise name on 2026-11-10: the set TJ records on the watch.
    Exercise("Check", "HYPEREXTENSION", "HYPEREXTENSION", (_TEN,)),
    # Three matching sets, so `workout.build` makes a repeat group (F-20a).
    Exercise("Check", "CURL", "CURL", (_TEN,) * 3, rest_seconds=60),
    # Two matching rounds of a superset, a repeat group of two exercises (F-26).
    Exercise("Check", "CRUNCH", "CRUNCH", (_TEN,) * 2, superset=1),
    Exercise("Check", "SQUAT", "SQUAT", (_TEN,) * 2, rest_seconds=60, superset=1),
)
STEP_SIZES = (250, 100, 50)  # the step probe's sizes, largest first; it stops at the first Garmin takes
# Rep targets no two rounds in a row share, so no repeat group shortens the probe.
_PROBE_REPS = (8, 10, 12, 10, 8)
_PROBE_PAIRS = (("CURL", "CURL"), ("CRUNCH", "CRUNCH"), ("SQUAT", "SQUAT"), ("LUNGE", "LUNGE"), ("ROW", "ROW"))
_REASON_LENGTH = 500  # how much of Garmin's reason the probe prints
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


def _body(name: str, steps: Sequence[Exercise], system: str | None) -> Json:
    return workout.build(Workout(workout.ROUTINE, "check", name, tuple(steps)), system) | {"description": DESCRIPTION}


def set_body(system: str | None) -> Json:
    """`HGS check set`, built by the app's own `workout.build`, as a routine of SET_EXERCISES would be."""
    return _body(SET_WORKOUT, SET_EXERCISES, system)


def steps_body(size: int, system: str | None) -> Json:
    """`HGS check steps` with `size` steps (a multiple of 10): five sets and their rests per exercise, no group."""
    probe = [
        Exercise("Check", *_PROBE_PAIRS[n % len(_PROBE_PAIRS)], tuple(Set(reps=r) for r in _PROBE_REPS))
        for n in range(size // (2 * len(_PROBE_REPS)))
    ]
    return _body(STEPS_WORKOUT, probe, system)


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
    """Every dict anywhere in a reply that has an `exerciseName`, in order, whatever the nesting."""
    if isinstance(node, dict):
        if "exerciseName" in node:
            yield node
        for value in node.values():
            yield from named_steps(value)
    elif isinstance(node, list):
        for item in node:
            yield from named_steps(item)


def compare(sent: Json, stored: Json) -> list[str]:
    """One line per set: the exercise sent and the one Garmin stored. Garmin's keys only.

    Should Garmin nest the stored steps in another way, the counts differ, and every step a plain
    walk finds is listed too, so the run still answers what Garmin stored.
    """
    out_steps, back_steps = list(sets(sent)), list(sets(stored))
    lines = []
    for number, (out, back) in enumerate(zip(out_steps, back_steps, strict=False), start=1):
        sent_pair = f"{out['category']} / {out['exerciseName']}"
        stored_pair = f"{back.get('category')} / {back.get('exerciseName')}"
        lines.append(f"Set {number}: sent {sent_pair}, Garmin stored {stored_pair}")
    if len(out_steps) != len(back_steps):
        lines.append(
            f"The counts differed: {len(out_steps)} steps sent, {len(back_steps)} found where the app reads them. "
            "Every step found anywhere in the stored workout:"
        )
        for found in named_steps(stored):
            lines.append(f"- category {found.get('category')}, exerciseName {found.get('exerciseName')}")
    return lines


def step_shapes(stored: Json) -> Json:
    """The shape of the first step of each kind in a stored workout, inside repeat groups too.

    Keyed by where the step is and its step type: `step.interval`, `group.repeat` (the group without
    its steps), `in_group.rest` and so on. `shape` alone keeps only a list's first item, so a group
    that is not the first step would be lost.
    """
    found: Json = {}

    def walk(steps: Sequence[Json], where: str) -> None:
        for step in steps:
            kind = str((step.get("stepType") or {}).get("stepTypeKey"))
            kind = kind if _KEY.fullmatch(kind) else "<key>"
            if isinstance(step.get("workoutSteps"), list):
                found.setdefault(f"group.{kind}", shape({k: v for k, v in step.items() if k != "workoutSteps"}))
                walk(step["workoutSteps"], "in_group")
            else:
                found.setdefault(f"{where}.{kind}", shape(step))

    for segment in stored.get("workoutSegments") or []:
        walk(segment.get("workoutSteps") or [], "step")
    return found


def refusal(error: ServiceError) -> str:
    """Garmin's status and its own reason for refusing a request, cut short. They hold no personal data."""
    status = getattr(getattr(error.__cause__, "response", None), "status_code", None)
    reason = str(error)[:_REASON_LENGTH]
    return f"{type(error).__name__}, HTTP {status}: {reason}" if status else f"{type(error).__name__}: {reason}"


def probe_steps(garmin: CheckGarmin, store: Store, created: list[int], system: str | None) -> list[str]:
    """Create `HGS check steps` at each of STEP_SIZES until Garmin takes one, deleting it at once.

    Never scheduled or sent. A refusal, or a failure on Garmin's side, is the answer for that size,
    so the probe goes on to the next.
    """
    lines = []
    for size in STEP_SIZES:
        body = steps_body(size, system)
        count = workout.step_count(body)
        try:
            probe_id = garmin.create(body)
        except (Refused, Unavailable) as e:
            lines.append(f"{count} steps: refused ({refusal(e)})")
            continue
        created.append(probe_id)
        save(store, CREATED, {"workouts": created})  # before the delete, so cleanup finds it should the run die
        lines.append(f"{count} steps: accepted")
        garmin.delete(probe_id)
        created.remove(probe_id)
        save(store, CREATED, {"workouts": created})
        break
    return lines


def save(store: Store, name: str, value: Any) -> None:
    store.write(name, json.dumps(value, indent=1, sort_keys=True) + "\n")


def check_garmin(garmin: CheckGarmin, store: Store, created: list[int], utcnow: Callable[[], datetime]) -> Json:
    """Make, read back, schedule and send `HGS check set`, then probe the step cap.

    `created` gets each id as it is made.
    """
    try:
        zone = ZoneInfo(garmin.time_zone() or "UTC")  # "today" as the app works it out with TZ unset (C-7)
    except ZoneInfoNotFoundError, ValueError, OSError:
        zone = ZoneInfo("UTC")
    today = utcnow().astimezone(zone).date()
    system = garmin.measurement_system()
    recorded: Json = {"settings": shape(garmin.settings())}

    sent = set_body(system)
    set_id = garmin.create(sent)
    created.append(set_id)
    save(store, CREATED, {"workouts": created})  # at once, so a failure later still leaves cleanup the id
    stored = garmin.stored(set_id)
    recorded["stored_workout"] = shape(stored)
    recorded["stored_steps"] = step_shapes(stored)
    recorded["sets"] = compare(sent, stored)

    recorded["schedule_reply"] = shape(garmin.schedule_reply(set_id, today))
    try:
        garmin.send_to_device(set_id)
        recorded["sent_to_the_watch"] = True
    except Refused:
        recorded["sent_to_the_watch"] = False  # no watch to send to; the calendar entry still stands (Sync._send)

    recorded["step_cap"] = probe_steps(garmin, store, created, system)

    listed = [w for w in garmin.workouts() if w.get("workoutId") == set_id]
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
            f"Garmin failed partway ({type(e).__name__}). {len(created)} check workouts are left in Garmin; "
            "run `make live-cleanup` to delete them and the saved Garmin token.",
            file=out,
        )
        return 1
    save(store, RECORDED, recorded)

    print(f"{SET_WORKOUT}:", file=out)
    for line in recorded["garmin"]["sets"]:
        print(line, file=out)
    print("Kinds of step Garmin stored: " + ", ".join(sorted(recorded["garmin"]["stored_steps"])), file=out)
    print(f"{STEPS_WORKOUT} (the step cap, each made and deleted at once):", file=out)
    for line in recorded["garmin"]["step_cap"]:
        print(line, file=out)
    print(f"\nSaved to live-check/{RECORDED}, which holds no values. Paste it into the PR:\n", file=out)
    print(json.dumps(recorded, indent=1, sort_keys=True), file=out)
    where = "and on its way to the watch" if recorded["garmin"]["sent_to_the_watch"] else "but was not sent to a watch"
    print(
        f"\n{SET_WORKOUT} is on today's calendar {where}. Start it on the watch and do its first set "
        "without changing the reps, then save the activity. Look at that set in Garmin Connect and on Strava, "
        "then run `make live-cleanup`.",
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
