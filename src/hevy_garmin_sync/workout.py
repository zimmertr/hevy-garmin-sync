"""A workout as the app plans it, and the Garmin Connect workout it becomes (spec sections 3 and 4).

The Garmin JSON is built here as plain dictionaries, field for field what was
sent to a Fenix 8 in the watch checks the spec records (F-20a, F-21a, F-26,
F-27). python-garminconnect's typed workout models would add pydantic to the
image and tie the Version hash (F-12) to that library's defaults.
"""

import hashlib
import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

Step = dict[str, Any]
Body = dict[str, Any]

ROUTINE = "routine"
TRAINER = "trainer"

# Garmin's profile setting `userData.measurementSystem` (F-21a). Only
# `statute_us` is known to mean pounds; `statute_uk` gets kilograms until
# someone confirms otherwise (U-14), and yards like the US setting.
STATUTE_US = "statute_us"
STATUTE_UK = "statute_uk"

FIRST_LINE = "Synced from Hevy: https://github.com/zimmertr/hevy-garmin-sync"
_ID_LABELS = {ROUTINE: "Hevy routine", TRAINER: "Hevy Trainer template"}
_ID_LINE = re.compile(r"(Hevy routine|Hevy Trainer template): (\S+)")
_VERSION_LINE = re.compile(r"Version: ([0-9a-f]{6})\b")

_POUNDS_PER_KG = 2.2046226218
_YARDS_PER_METER = 1.0936133

_STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training"}
_WARMUP = {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1}
_INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
_REST = {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}
_REPEAT = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}
_LAP_BUTTON = {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}
_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
_ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}
_REPS = {"conditionTypeId": 10, "conditionTypeKey": "reps", "displayOrder": 10, "displayable": True}
_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_SET_LABELS = {"warmup": "Warm-up", "dropset": "Drop set", "failure": "To failure"}


@dataclass(frozen=True)
class Set:
    kind: str = "normal"  # Hevy's set types: normal, warmup, dropset, failure
    reps: int | None = None
    rep_range: tuple[int, int] | None = None
    weight_kg: float | None = None
    seconds: int | None = None
    meters: float | None = None


@dataclass(frozen=True)
class LoggedSet:
    """A working set as Hevy logged it, for the note's lines of last time's numbers (previous.py)."""

    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None
    seconds: int | None = None
    meters: float | None = None


@dataclass(frozen=True)
class Exercise:
    title: str  # Hevy's title, for the note on a timed set's wait step
    category: str  # Garmin's exercise category key
    name: str  # Garmin's exercise key
    sets: tuple[Set, ...]
    rest_seconds: int | None = None
    superset: int | None = None
    assisted: bool = False
    previous: tuple[LoggedSet, ...] = ()  # the working sets of the last session that logged it


@dataclass(frozen=True)
class Workout:
    kind: str  # ROUTINE or TRAINER
    source_id: str  # the Hevy routine id, or the Trainer template id
    name: str
    exercises: tuple[Exercise, ...]


@dataclass(frozen=True)
class Owner:
    """What the description of one of the app's Garmin workouts says (F-12)."""

    kind: str
    source_id: str
    version: str | None


def build(workout: Workout, measurement_system: str | None) -> Body:
    """The Garmin workout, without its description."""
    blocks: list[list[Step]] = []
    for group in _supersets(workout.exercises):
        blocks.extend(_grouped(_rounds(group, measurement_system)))
    steps = [step for block in blocks for step in block]
    _number(steps)
    return {
        "workoutName": workout.name,
        "sportType": _STRENGTH,
        "estimatedDurationInSecs": 0,
        "workoutSegments": [{"segmentOrder": 1, "sportType": _STRENGTH, "workoutSteps": steps}],
        "author": {},
    }


def version(body: Body) -> str:
    """A short hash of the workout exactly as the app built it (F-12)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:6]


def stamped(body: Body, workout: Workout, now: datetime) -> Body:
    """The body with the ownership description (F-12). `now` is in the user's zone."""
    lines = [
        FIRST_LINE,
        f"Last updated: {now.strftime('%Y-%m-%d %H:%M %Z')}",
        f"{_ID_LABELS[workout.kind]}: {workout.source_id}",
        f"Version: {version(body)}",
    ]
    return body | {"description": "\n".join(lines)}


def owner(description: str | None) -> Owner | None:
    """Who a Garmin workout belongs to, or None when it isn't the app's.

    Matched by pattern, not by line number, so the answer does not depend on
    how Garmin stores the line breaks.
    """
    if not description or not description.startswith(FIRST_LINE):
        return None
    found = _ID_LINE.search(description)
    if not found:
        return None
    kind = ROUTINE if found.group(1) == _ID_LABELS[ROUTINE] else TRAINER
    ver = _VERSION_LINE.search(description)
    return Owner(kind, found.group(2), ver.group(1) if ver else None)


def step_count(body: Body) -> int:
    """Every step Garmin stores, repeat groups and the steps inside them included (F-16)."""

    def count(steps: Sequence[Step]) -> int:
        return sum(1 + count(step.get("workoutSteps", ())) for step in steps)

    return count(body["workoutSegments"][0]["workoutSteps"])


def _supersets(exercises: Sequence[Exercise]) -> Iterator[list[Exercise]]:
    """Exercises in order, each superset gathered where its first exercise is (F-26)."""
    seen: set[int] = set()
    for exercise in exercises:
        if exercise.superset is None:
            yield [exercise]
        elif exercise.superset not in seen:
            seen.add(exercise.superset)
            yield [e for e in exercises if e.superset == exercise.superset]


def _rounds(group: Sequence[Exercise], system: str | None) -> list[list[Step]]:
    """One block of steps per round: set i of every exercise that still has one.

    An exercise outside a superset is a group of one, so its rounds are its
    sets. Every set is followed by a rest step, the workout's last included,
    because the watch only asks for reps and weight when one follows (F-29).
    Inside a round the rest is open, so that prompt comes up before the next
    exercise; the round ends on its last exercise's rest timer (F-26).
    """
    rounds = []
    for i in range(max((len(e.sets) for e in group), default=0)):
        members = [e for e in group if len(e.sets) > i]
        block: list[Step] = []
        for exercise in members:
            current = exercise.sets[i]
            if current.seconds:
                block.append(_wait_step(exercise, current))
            block.append(_set_step(exercise, current, system))
            block.append(_rest_step(exercise.rest_seconds if exercise is members[-1] else None))
        rounds.append(block)
    return rounds


def _grouped(rounds: Sequence[list[Step]]) -> Iterator[list[Step]]:
    """Back-to-back rounds that match exactly become one repeat group (F-20a)."""
    i = 0
    while i < len(rounds):
        n = 1
        while i + n < len(rounds) and rounds[i + n] == rounds[i]:
            n += 1
        if n == 1:
            yield rounds[i]
        else:
            yield [
                {
                    "type": "RepeatGroupDTO",
                    "stepType": _REPEAT,
                    "numberOfIterations": n,
                    "workoutSteps": rounds[i],
                    "endCondition": _ITERATIONS,
                    "endConditionValue": float(n),
                    "smartRepeat": False,
                    # Never skip it: the last round's prompt depends on its rest step (F-29).
                    "skipLastRestStep": False,
                }
            ]
        i += n


def _number(steps: Sequence[Step]) -> None:
    """Number every step once, in order; a repeat group and its steps share a `childStepId`."""
    order = 0
    groups = 0
    for step in steps:
        order += 1
        step["stepOrder"] = order
        if "workoutSteps" in step:
            groups += 1
            step["childStepId"] = groups
            for child in step["workoutSteps"]:
                order += 1
                child["stepOrder"] = order
                child["childStepId"] = groups


def _set_step(exercise: Exercise, current: Set, system: str | None) -> Step:
    step: Step = {
        "type": "ExecutableStepDTO",
        # Garmin stores the warm-up mark but the watch never shows it, so the note says it too (F-24).
        "stepType": _WARMUP if current.kind == "warmup" else _INTERVAL,
        "targetType": _NO_TARGET,
        "category": exercise.category,
        "exerciseName": exercise.name,
    }
    reps = current.rep_range[1] if current.rep_range else current.reps
    if current.seconds:
        step["endCondition"] = _TIME
        step["endConditionValue"] = float(current.seconds)
    elif reps and not current.meters:
        step["endCondition"] = _REPS
        step["endConditionValue"] = float(reps)
    else:
        # No rep target, or a distance: a distance end condition is useless
        # indoors, so the set ends on a button press (F-22, F-27).
        step["endCondition"] = _LAP_BUTTON
        step["endConditionValue"] = None
    if current.weight_kg:
        # In the user's own unit: the library's kilogram helper shows as 0.0 lbs on the watch (F-21a).
        if system == STATUTE_US:
            step["weightValue"] = round(current.weight_kg * _POUNDS_PER_KG, 2)
            step["weightUnit"] = {"unitId": 7, "unitKey": "pound"}
        else:
            step["weightValue"] = float(current.weight_kg)
            step["weightUnit"] = {"unitId": 8, "unitKey": "kilogram"}
    note = _note(current, exercise, system)
    if note:
        step["description"] = note
    return step


def _rest_step(seconds: int | None) -> Step:
    """A timed rest, or one that waits for a button press when there is no timer (F-23)."""
    step: Step = {"type": "ExecutableStepDTO", "stepType": _REST, "targetType": _NO_TARGET}
    if seconds:
        step["endCondition"] = _TIME
        step["endConditionValue"] = float(seconds)
    else:
        step["endCondition"] = _LAP_BUTTON
        step["endConditionValue"] = None
    return step


def _wait_step(exercise: Exercise, current: Set) -> Step:
    """A timed set counts down the instant the step before it ends, so the user starts it (F-27)."""
    return _rest_step(None) | {
        "description": f"Press Lap button to start {_length(current.seconds or 0)} {exercise.title} countdown"
    }


def _length(total: int) -> str:
    """A duration as the watch's notes spell it: 45s, 1m, 1m 30s."""
    minutes, seconds = divmod(total, 60)
    return " ".join(part for part in (f"{minutes}m" if minutes else "", f"{seconds}s" if seconds else "") if part)


def _distance(meters: float, system: str | None) -> str:
    yards = system in (STATUTE_US, STATUTE_UK)
    return f"{round(meters * _YARDS_PER_METER)} yd" if yards else f"{round(meters)} m"


def _note(current: Set, exercise: Exercise, system: str | None) -> str | None:
    """The one note a set carries: its type, its rep range or distance (F-30), then last time's sets (F-30b).

    Each on a line of its own, so the watch breaks none of them in two: it
    wrapped `Drop set: 4-6 reps`, 18 characters, and left `reps` on a line by
    itself (TJ, 2026-11-11, #3).
    """
    label = _SET_LABELS.get(current.kind, "")
    if exercise.assisted:
        label = f"{label}, assisted" if label else "Assisted"
    goal = ""
    if current.meters:
        goal = f"Goal: {_distance(current.meters, system)}"
    elif current.rep_range and current.rep_range[0] != current.rep_range[1]:
        goal = f"Goal: {current.rep_range[0]}-{current.rep_range[1]} reps"
    # Every working set of an exercise gets the same block, so matching sets still share a repeat group (F-20a).
    previous = "" if current.kind == "warmup" else _previous(exercise.previous, system)
    return "\n".join(part for part in (label, goal, previous) if part) or None


def _previous(logged: Sequence[LoggedSet], system: str | None) -> str:
    """Last time's working sets, one to a line under a heading that names the unit once, or "" for none.

    The form was settled on a Fenix 8 (TJ, 2026-11-11, #3): a line holds 14
    digits and wraps at a space, so a line of more than 8 digits drops the
    spaces after `x` and `@` to stay whole.
    """
    pounds = system == STATUTE_US  # the unit the weights go to Garmin in (F-21a)
    lines = []
    weighed = False
    for done in logged:
        weight = ""
        if done.weight_kg:
            weight = f"{round(done.weight_kg * _POUNDS_PER_KG if pounds else done.weight_kg, 1):g}"
        amount = ""
        if done.reps:
            amount = str(done.reps)
        elif done.seconds:
            amount = _length(done.seconds)
        elif done.meters:
            amount = _distance(done.meters, system)
        if not (weight or amount):
            continue  # a set logged with nothing in it has nothing to show
        weighed = weighed or bool(weight)
        rpe = f"{done.rpe:g}" if done.rpe else ""
        spaced = _line(weight, amount, rpe, " ")
        lines.append(spaced if sum(c.isdigit() for c in spaced) <= 8 else _line(weight, amount, rpe, ""))
    if not lines:
        return ""
    unit = (" (lb)" if pounds else " (kg)") if weighed else ""
    # "Previous" is Hevy's own word for the column, and 14 characters with the unit fit one line of the watch.
    return "\n".join([f"Previous{unit}:", *lines])


def _line(weight: str, amount: str, rpe: str, gap: str) -> str:
    """`65 x 6 @ 7.5` with `gap` a space, `65 x6 @7.5` with it empty."""
    line = f"{weight} x{gap}{amount}" if weight and amount else weight or amount
    return f"{line} @{gap}{rpe}" if rpe else line
