"""One run by hand against TJ's own accounts, for the open points in docs/DATA.md. CI never runs it.

`make live-check` runs `record`, and `make live-cleanup` runs `cleanup` once the watch has been
looked at. `make live-check-hevy` runs `record-hevy`, and `make live-check-notes` runs `notes`. All
run in Docker, from a clone, on TJ's machine.

`record`:
1. Reads Hevy's public API with HEVY_API_KEY, and Hevy's private API when HEVY_SESSION is set
   (a fresh cookie from a private window, never the pod's), and keeps the shape of each reply.
   The exercise template and its history are read for the first exercise of a routine, else of
   a logged workout. For Hevy Trainer it also keeps `next_workout_index` and the templates'
   `index` values, which the calendar rule reads (spec F-31), and prints, per template, whether
   each of its `edits` (an exercise swapped in the Hevy app) is already in its `exercises`, and
   how many minutes ago the program last changed. It also reads `user_key_values`, Hevy's per-user
   store, where a swap "for this workout only" may be kept, and prints each entry's key name,
   value type and the shape of a value holding JSON; for an entry whose key names Trainer, a
   workout, an exercise or a swap, whether the program's ids, or an exercise id not in the
   program, occur in it. A refusal there is recorded and the run goes on.
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

`notes` checks each set's note as the app writes it (spec F-30): one Garmin sign-in and no Hevy
read. It creates `HGS check notes`, built by the app's own `workout.build`: a warm-up and a Normal Set
whose Garmin name differs from Hevy's, a Failure Set with a decimal weight, a Drop Set, a timed set,
and one set whose note ends with a line of symbols, to see which ones the watch's font draws. It reads
the workout back and says whether Garmin stored every note whole, then puts it on today and sends it
to the watch. `cleanup` removes it like the others.

Safety, enforced in code:
- Never writes to Hevy: only the read methods of `Hevy` and `HevyPrivate` are called.
- Deletes and unschedules only its own workouts: a Garmin workout that carries one of the three
  names and, when live-check/created.json is there, one of the ids it lists. Each id is saved there
  the moment the workout exists. The workouts' description is not the app's (`workout.owner` gives
  None), so the running app never claims or deletes them.
- Prints and saves shapes, never a value: `shape` keeps keys and type names, and replaces any key
  that could itself be a value, such as an id or a date, with `<key>`. The only values out are
  Garmin's exercise and step type keys, the step counts tried, the two Trainer index values above,
  for Trainer's edits their type word, two yes-or-no answers, exercise counts and minutes, and the
  key names of `user_key_values`, with any id or the username in them shown as `<id>`.
  Errors print their type only, but for Garmin refusing the step probe: there the status and
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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Self, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import garminconnect
import requests

from hevy_garmin_sync import login, trainer, workout
from hevy_garmin_sync.errors import ConfigError, Refused, ServiceError, Unavailable
from hevy_garmin_sync.garmin import TOKENS, Garmin
from hevy_garmin_sync.hevy import Hevy
from hevy_garmin_sync.hevy_private import _WORKOUT_PAGE, HevyPrivate, parse_cookie, parse_time
from hevy_garmin_sync.store import Store
from hevy_garmin_sync.workout import Exercise, Set, Workout

FOLDER = Path(__file__).resolve().parents[1] / "live-check"
RECORDED = "recorded.json"
HEVY_RECORDED = "recorded-hevy.json"  # `record-hevy`'s, so it never overwrites what `record` saved
CREATED = "created.json"
SET_WORKOUT = "HGS check set"
STEPS_WORKOUT = "HGS check steps"
NOTES_WORKOUT = "HGS check notes"
NAMES = (SET_WORKOUT, STEPS_WORKOUT, NOTES_WORKOUT)
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
# `HGS check notes`: the notes the app writes, one of each shape (F-30; TJ, 2026-11-13). The weights
# are pounds as Hevy stores them, in kilograms.
_LB = 2.2046226218
CHECK_NOTES = (
    Exercise(
        "Seal Row (Dumbbell)",
        "ROW",
        "CHEST_SUPPORTED_DUMBBELL_ROW",
        (Set(kind="warmup", rep_range=(4, 6), weight_kg=35 / _LB), Set(rep_range=(4, 6), weight_kg=90 / _LB)),
    ),
    Exercise(
        "Pullover (Dumbbell)",
        "TRICEPS_EXTENSION",
        "LYING_DUMBBELL_PULLOVER_TO_EXTENSION",
        (Set(kind="failure", reps=8, weight_kg=17.5 / _LB),),
    ),
    Exercise("Hammer Curl (Dumbbell)", "CURL", "DUMBBELL_HAMMER_CURL", (Set(kind="dropset", rep_range=(8, 12)),)),
    Exercise("Plank", "PLANK", "PLANK", (Set(seconds=30),)),
    Exercise("Crunch", "CRUNCH", "CRUNCH", (Set(reps=10),)),
)
# Appended to the last note: which of these the watch draws decides whether a note can use them.
SYMBOLS = "x \u00d7 \u2022 \u2192 \u2713 \u00b0 \u00bd\n\u2605 \u2665 \u26a0 \u2013 \u2026 \u2265\n\U0001f4aa \U0001f3cb"
STEP_SIZES = (250, 100, 50)  # the step probe's sizes, largest first; it stops at the first Garmin takes
# Rep targets no two rounds in a row share, so no repeat group shortens the probe.
_PROBE_REPS = (8, 10, 12, 10, 8)
_PROBE_PAIRS = (("CURL", "CURL"), ("CRUNCH", "CRUNCH"), ("SQUAT", "SQUAT"), ("LUNGE", "LUNGE"), ("ROW", "ROW"))
_REASON_LENGTH = 500  # how much of Garmin's reason the probe prints
CALENDAR_DAYS = 31  # how far either side of today `cleanup` looks for the check workouts' entries
_KEY = re.compile(r"[a-z][A-Za-z_]*")  # a key that names a field; anything else may be a value
# `user_key_values`, where a one-off Trainer swap may be kept: the key names printed as sent, the
# ones worth searching for the program's ids, and how many entries the run lists.
_STORE_KEY = re.compile(r"[A-Za-z0-9_.:-]+")
_STORE_HINTS = ("trainer", "workout", "swap", "replace", "edit", "exercise")
_STORE_LIMIT = 60

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


def trainer_edits(program: Json | None, now: datetime) -> Json:
    """Whether each template's `edits` are already in its `exercises`, with no id, title or date.

    Per template in `index` order: its exercise count, and for each edit its `type` and whether its
    `from_` and `to_exercise_template_id` are among the template's exercises. A swap applied to
    `exercises` has its `to` there and its `from` gone. Beside them, how many whole minutes ago the
    program's `updated_at` was, to show whether the swap touched the program at all.
    """
    templates = sorted((program or {}).get("templates") or [], key=lambda t: t.get("index") or 0)
    found = []
    for template in templates:
        listed = template.get("exercises") or []
        ids = {e.get("exercise_template_id") for e in listed}
        edits = []
        for edit in template.get("edits") or []:
            kind = edit.get("type")
            edits.append(
                {
                    # Hevy's enum word; anything else shows as its type, in case it is not one.
                    "type": kind if isinstance(kind, str) and _KEY.fullmatch(kind) else type(kind).__name__,
                    "from_in_exercises": edit.get("from_exercise_template_id") in ids,
                    "to_in_exercises": edit.get("to_exercise_template_id") in ids,
                }
            )
        found.append({"exercise_count": len(listed), "edits": edits})
    updated = parse_time((program or {}).get("updated_at"))
    minutes = int((now - updated).total_seconds() // 60) if updated else "NoneType"
    return {"program_updated_minutes_ago": minutes, "templates": found}


def edit_lines(edits: Json) -> list[str]:
    ago = edits["program_updated_minutes_ago"]
    lines = [f"Program updated {ago} minutes ago" if isinstance(ago, int) else f"Program's updated_at: {ago}"]
    for number, template in enumerate(edits["templates"], start=1):
        head = f"Template {number} ({template['exercise_count']} exercises):"
        if not template["edits"]:
            lines.append(f"{head} no edits")
        for edit in template["edits"]:
            lines.append(
                f"{head} {edit['type']}, from in exercises {edit['from_in_exercises']}, "
                f"to in exercises {edit['to_in_exercises']}"
            )
    return lines


@dataclass(frozen=True)
class ProgramIds:
    """The program's template and exercise template ids, and the form of the latter, to look for in a value."""

    templates: frozenset[str]
    exercises: frozenset[str]

    @classmethod
    def of(cls, program: Json | None) -> Self:
        templates = (program or {}).get("templates") or []
        return cls(
            frozenset(str(t["id"]) for t in templates if t.get("id")),
            frozenset(
                str(e["exercise_template_id"])
                for t in templates
                for e in t.get("exercises") or []
                if e.get("exercise_template_id")
            ),
        )

    def look_alikes(self, text: str) -> list[str]:
        """Each run of `text` with an exercise id's length and characters, known or not."""
        chars = "".join(sorted(set("".join(self.exercises))))
        if not chars:
            return []
        lengths = {len(i) for i in self.exercises}
        return [run for run in re.findall(f"[{re.escape(chars)}]+", text) if len(run) in lengths]


def _parsed(text: str) -> tuple[bool, Any]:
    try:
        return True, json.loads(text)
    except ValueError:
        return False, None


def _strings(node: Any) -> Iterator[str]:
    """Every string anywhere in a value, dict keys included, and inside a string that holds JSON."""
    if isinstance(node, dict):
        for key, item in node.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, str):
        yield node
        ok, parsed = _parsed(node)
        if ok and isinstance(parsed, dict | list):
            yield from _strings(parsed)


def mentions(key: str, value: Any, ids: ProgramIds) -> Json:
    """Whether the program's ids, or a stranger in their form, occur in an entry: three yes-or-no answers."""
    texts = [key, *_strings(value)]
    known = ids.templates | ids.exercises
    return {
        "mentions_a_template_id": any(i in t for t in texts for i in ids.templates),
        "mentions_a_program_exercise_id": any(i in t for t in texts for i in ids.exercises),
        # What an exercise swapped in for one workout would look like.
        "mentions_an_exercise_id_not_in_the_program": any(
            run not in known for t in texts for run in ids.look_alikes(t)
        ),
    }


def store_key(key: Any, ids: ProgramIds, username: str) -> str:
    """A key's name as sent, when it is a plain name, with any id or the username in it hidden."""
    name = key if isinstance(key, str) else ""
    if not _STORE_KEY.fullmatch(name):
        return "<key>"
    for hidden in sorted((ids.templates | ids.exercises | {username}) - {""}, key=len, reverse=True):
        name = name.replace(hidden, "<id>")
    for run in ids.look_alikes(name):
        name = name.replace(run, "<id>")
    return name


def read_store(private: HevyPrivate, program: Json | None, username: str) -> tuple[Any, Json]:
    """`user_key_values`: its shape, and per entry its key name, value type and, for a value holding JSON,
    that JSON's shape. An entry whose key names Trainer, a workout, an exercise or a swap also says whether
    the program's ids occur in it. A refusal is recorded, never fatal: the call is a guess.
    """
    try:
        reply = private._get("user_key_values")
    except ServiceError as e:
        status = re.match(r"HTTP (\d+)", str(e))  # the status only: the rest of the text is Hevy's reply
        refused = f"refused ({type(e).__name__}, HTTP {status.group(1) if status else 'none'})"
        return refused, {"form": refused, "entries": [], "more": 0}
    if isinstance(reply, dict):
        form, rows = "a dict of keys", list(reply.items())
    elif isinstance(reply, list):
        form = "a list of rows"
        rows = [(row.get("key"), row.get("value")) if isinstance(row, dict) else (None, row) for row in reply]
    else:
        form, rows = type(reply).__name__, []
    ids = ProgramIds.of(program)
    entries = []
    for key, value in rows[:_STORE_LIMIT]:
        entry: Json = {"key": store_key(key, ids, username), "value_type": type(value).__name__}
        if isinstance(value, str):
            ok, parsed = _parsed(value)
            if ok:
                entry["json_shape"] = shape(parsed)
        if isinstance(key, str) and any(hint in key.lower() for hint in _STORE_HINTS):
            entry |= mentions(key, value, ids)
        entries.append(entry)
    # A dict's own keys may be anything, so they reach the shape only as `store_key` writes them.
    named = {store_key(k, ids, username): v for k, v in reply.items()} if isinstance(reply, dict) else reply
    return shape(named), {"form": form, "entries": entries, "more": max(0, len(rows) - _STORE_LIMIT)}


def store_lines(store: Json) -> list[str]:
    if not store["entries"] and store["form"].startswith("refused"):
        return [store["form"]]
    lines = [f"Hevy sent {store['form']}, {len(store['entries']) + store['more']} entries:"]
    for entry in store["entries"]:
        line = f"- {entry['key']}: {entry['value_type']}"
        if "json_shape" in entry:
            line += f", JSON {json.dumps(entry['json_shape'], sort_keys=True)}"
        if "mentions_a_template_id" in entry:
            line += (
                f"; a template id {entry['mentions_a_template_id']}, a program exercise id "
                f"{entry['mentions_a_program_exercise_id']}, an exercise id not in the program "
                f"{entry['mentions_an_exercise_id_not_in_the_program']}"
            )
        lines.append(line)
    if store["more"]:
        lines.append(f"and {store['more']} more")
    return lines


def read_trainer(private: HevyPrivate, now: datetime) -> Json:
    """The shapes of the private replies, the two index values the calendar rule reads, `trainer_edits`
    and `read_store`'s entries, each under its own key of the recorded file."""
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
    shapes["user_key_values"], store = read_store(private, program, str(user.get("username") or ""))
    return {
        "hevy_trainer": shapes,
        "hevy_trainer_order": order,
        "hevy_trainer_edits": trainer_edits(program, now),
        "hevy_trainer_key_values": store,
    }


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


def notes_body(system: str | None) -> Json:
    """`HGS check notes`: the app's own steps and notes, and a line of SYMBOLS after the last one."""
    body = _body(NOTES_WORKOUT, CHECK_NOTES, system)
    last = list(sets(body))[-1]
    last["description"] = f"{last['description']}\n{SYMBOLS}"
    return body


def notes_kept(sent: Json, stored: Json) -> list[str]:
    """Whether Garmin stored each note as sent: one line for each it changed, else one line saying none."""
    changed = [
        f"Garmin stored {len(back.get('description') or '')} of the {len(out['description'])} characters of "
        f"exercise {number}'s note."
        for number, (out, back) in enumerate(zip(sets(sent), sets(stored), strict=False), start=1)
        if back.get("description") != out["description"]
    ]
    return changed or ["Garmin stored every note whole."]


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


def _today(garmin: CheckGarmin, utcnow: Callable[[], datetime]) -> date:
    """Today as the app works it out with TZ unset (C-7): in the Garmin profile's zone, else UTC."""
    try:
        zone = ZoneInfo(garmin.time_zone() or "UTC")
    except ZoneInfoNotFoundError, ValueError, OSError:
        zone = ZoneInfo("UTC")
    return utcnow().astimezone(zone).date()


def check_garmin(garmin: CheckGarmin, store: Store, created: list[int], utcnow: Callable[[], datetime]) -> Json:
    """Make, read back, schedule and send `HGS check set`, then probe the step cap.

    `created` gets each id as it is made.
    """
    today = _today(garmin, utcnow)
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


_NOT_CLEANED_UP = "live-check/created.json is from an earlier run: run `make live-cleanup` first."
_SIGN_IN_ERRORS = (
    garminconnect.GarminConnectTooManyRequestsError,
    garminconnect.GarminConnectAuthenticationError,
    garminconnect.GarminConnectConnectionError,
)


def _partway(error: Exception, created: Sequence[int]) -> str:
    return (
        f"Garmin failed partway ({type(error).__name__}). {len(created)} check workouts are left in Garmin; "
        "run `make live-cleanup` to delete them and the saved Garmin token."
    )


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
        print(_NOT_CLEANED_UP, file=out)
        return 1
    recorded = read_all_hevy(env, out, ask, hevy_session, private_session, utcnow)
    if recorded is None:
        return 1
    save(store, RECORDED, recorded)

    try:
        token = sign_in()
    except _SIGN_IN_ERRORS as e:
        print(
            f"The Garmin sign-in failed ({type(e).__name__}). Hevy's shapes are saved; nothing was made in Garmin.",
            file=out,
        )
        return 1
    created: list[int] = []
    try:
        recorded["garmin"] = check_garmin(open_garmin(token, store), store, created, utcnow)
    except (ServiceError, ConfigError) as e:
        print(_partway(e, created), file=out)
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
                recorded |= read_trainer(private, utcnow())
    except ConfigError as e:
        print(f"{e}. Nothing was made in Garmin.", file=out)  # the app's own words, which hold no value
        return None
    except ServiceError as e:
        print(f"Reading Hevy failed ({type(e).__name__}). Nothing was made in Garmin.", file=out)
        return None
    if "hevy_trainer_edits" in recorded:
        print("Hevy Trainer edits, per template in index order (is each edit already in its exercises?):", file=out)
        for line in edit_lines(recorded["hevy_trainer_edits"]):
            print(line, file=out)
        print(file=out)
        print(
            "Hevy user_key_values, where a one-off swap may be kept (key names, types and shapes, no values):",
            file=out,
        )
        for line in store_lines(recorded["hevy_trainer_key_values"]):
            print(line, file=out)
        print(file=out)
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


def check_notes(
    folder: Path,
    out: TextIO,
    *,
    sign_in: Callable[[], str] = login.sign_in,
    open_garmin: OpenGarmin = CheckGarmin.open,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Put `HGS check notes` on today and send it to the watch: one Garmin sign-in, and Hevy is never read."""
    store = Store(folder)
    if store.read(CREATED) is not None:
        print(_NOT_CLEANED_UP, file=out)
        return 1
    try:
        token = sign_in()
    except _SIGN_IN_ERRORS as e:
        print(f"The Garmin sign-in failed ({type(e).__name__}). Nothing was made in Garmin.", file=out)
        return 1
    created: list[int] = []
    try:
        garmin = open_garmin(token, store)
        today = _today(garmin, utcnow)
        body = notes_body(garmin.measurement_system())
        notes_id = garmin.create(body)
        created.append(notes_id)
        save(store, CREATED, {"workouts": created})  # at once, so a failure later still leaves cleanup the id
        kept = notes_kept(body, garmin.stored(notes_id))
        garmin.schedule(notes_id, today)
        try:
            garmin.send_to_device(notes_id)
            where = "and on its way to the watch"
        except Refused:
            where = "but was not sent to a watch"  # no watch to send to; the calendar entry still stands
    except (ServiceError, ConfigError) as e:
        print(_partway(e, created), file=out)
        return 1

    print(f"{NOTES_WORKOUT} is on today's calendar {where}. Its exercises and their notes, line by line:", file=out)
    for number, step in enumerate(sets(body), start=1):
        name = workout.garmin_name(step["category"], step["exerciseName"])
        print(f"{number}. {name}: {step['description'].replace('\n', ' / ')}", file=out)
    for line in kept:
        print(line, file=out)
    print(
        "\nSync the watch and start it. During each set, open the note's own screen and photograph it. Does "
        "each line stay whole? Does the Hevy name wrap cleanly? Does the warm-up wait for the Lap press? "
        "Which symbols in the last note does the watch draw? Then discard the activity and run "
        "`make live-cleanup`.",
        file=out,
    )
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
    parser.add_argument("command", choices=("record", "record-hevy", "notes", "cleanup"))
    args = parser.parse_args(argv)
    if args.command == "record":
        return record(env, FOLDER, out)
    if args.command == "record-hevy":
        return record_hevy(env, FOLDER, out)
    if args.command == "notes":
        return check_notes(FOLDER, out)
    return cleanup(FOLDER, out)


if __name__ == "__main__":  # pragma: no cover (the tests call main(); this line only runs from a shell)
    raise SystemExit(main())
