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
from dataclasses import dataclass, field
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
_UPDATED_LINE = re.compile(r"Last updated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})")

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
# Hevy's own names for its set types (TJ, 2026-11-13).
_SET_LABELS = {"normal": "Normal Set", "warmup": "Warm Up Set", "dropset": "Drop Set", "failure": "Failure Set"}


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
    """A working set as Hevy logged it, for the status page's line of last time's numbers (previous.py)."""

    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None
    seconds: int | None = None
    meters: float | None = None


@dataclass(frozen=True)
class Exercise:
    title: str  # Hevy's title, for the notes when it differs from Garmin's name
    category: str  # Garmin's exercise category key
    name: str  # Garmin's exercise key
    sets: tuple[Set, ...]
    rest_seconds: int | None = None
    superset: int | None = None
    assisted: bool = False
    # For the status page only, never sent to Garmin (spec W-2), so they take no part in
    # comparing plans: the working sets of the last session that logged it, what chose the
    # Garmin exercise, and Hevy Trainer's direction, or why it gave no weight.
    previous: tuple[LoggedSet, ...] = field(default=(), compare=False)
    chosen_by: str = field(default="", compare=False)
    direction: str | None = field(default=None, compare=False)
    no_weight: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Workout:
    kind: str  # ROUTINE or TRAINER
    source_id: str  # the Hevy routine id, or the Trainer template id
    name: str
    exercises: tuple[Exercise, ...]
    # For the status page only (W-2): the routine's or template's own name, and the routine's Hevy folder.
    title: str = field(default="", compare=False)
    folder: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Owner:
    """What the description of one of the app's Garmin workouts says (F-12)."""

    kind: str
    source_id: str
    version: str | None
    updated: datetime | None = None  # the wall-clock time of the last write, in the user's zone but without it


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
    updated = _UPDATED_LINE.search(description)
    return Owner(
        kind,
        found.group(2),
        ver.group(1) if ver else None,
        datetime.strptime(updated.group(1), "%Y-%m-%d %H:%M") if updated else None,
    )


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
    step["description"] = _note(current, exercise, system)
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


def _note(current: Set, exercise: Exercise, system: str | None) -> str:
    """The set as Garmin's own set-info screen shows it, under Hevy's name for the set type (F-30).

    The set-info screen is buried in the step list, while the note is one
    page down during the set (TJ, 2026-11-13). Each part has a line of its
    own, so the watch breaks none of them in two, and Hevy's exercise name goes
    last, where a long one can wrap. Matching sets get matching notes, so they
    still share a repeat group (F-20a).
    """
    lines = [_SET_LABELS.get(current.kind, "Normal Set")]
    if current.rep_range or current.reps:
        low, high = current.rep_range or (current.reps or 0, current.reps or 0)
        count = f"{low}-{high}" if low != high else str(high)
        lines.append(f"{count} {'Rep' if count == '1' else 'Reps'}")
    if current.seconds:
        lines.append(_clock(current.seconds))
    if current.meters:
        lines.append(_distance(current.meters, system))
    if current.weight_kg:
        weight = _weight(current.weight_kg, system)
        lines.append(f"Assisted {weight}" if exercise.assisted else weight)
    elif exercise.assisted:
        lines.append("Assisted")
    # Only when Garmin's name says something Hevy's doesn't: `Arnold Press` for `Arnold Press (Dumbbell)` is no news.
    if not _words(garmin_name(exercise.category, exercise.name)) <= _words(exercise.title):
        lines.append(f"Hevy: {exercise.title}")
    return "\n".join(lines)


def _clock(total: int) -> str:
    """A duration as the watch counts it down: 0:30, 1:30."""
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def _weight(kg: float, system: str | None) -> str:
    """`35 lbs`, `17.5 lbs` or `1.25 kg`: whole unless Hevy has a fraction, in the unit sent to Garmin (F-21a)."""
    if system == STATUTE_US:
        return f"{round(kg * _POUNDS_PER_KG, 2):g} lbs"
    return f"{round(kg, 2):g} kg"


def garmin_name(category: str, name: str) -> str:
    """Garmin's key as words: BARBELL_BACK_SQUAT is Barbell Back Squat."""
    return (name or category).replace("_", " ").title()


def _words(title: str) -> set[str]:
    """A name's words, any order and singular, so `Bicep Curl (Dumbbell)` holds Garmin's `Dumbbell Biceps Curl`.

    Garmin spells dumbbell `DUMBELL` in some keys, and joins words with `WITH`.
    """
    words = {w.replace("dumbell", "dumbbell") for w in re.findall(r"[a-z0-9]+", title.lower())}
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words} - {"with"}
