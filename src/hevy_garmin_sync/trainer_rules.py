"""Hevy Trainer's arithmetic: the program week, the next weight, the next rep range, the warm-ups (spec F-41 to F-47).

Hevy's servers send a Trainer program without weights or a week number; the
Hevy app works those out on the phone. These functions give the same answers,
so the watch shows what the app shows. Every rule and constant here is written
down in docs/HEVY_TRAINER_RULES.md, with the cases checked against the app.

Pure functions, no I/O. A weight is in the exercise's own unit (`lbs` or `kg`)
unless its name ends in `_kg`.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

LBS_PER_KG = 2.20462
CYCLE_WEEKS = 6
REP_LADDER = ((4, 6), (6, 8), (8, 12), (12, 15), (15, 20), (20, 25), (25, 30))
WARMUP_SHARES: dict[int, tuple[float, ...]] = {0: (), 1: (0.6,), 2: (0.4, 0.6)}
DELOAD_SHARE = 0.6
STEP_UP, STEP_DOWN = 1.05, 0.95
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
# What rounding uses where Trainer's preferences list nothing.
DEFAULT_WEIGHTS: dict[str, list[float]] = {
    "platesKg": [25, 20, 15, 10, 5, 2.5, 1.25],
    "platesLbs": [45, 25, 10, 5, 2.5],
    "barsKg": [20],
    "barsLbs": [45],
    "dumbbellsKg": [2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 35, 40, 45, 50],
    "dumbbellsLbs": [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100],
}
MACHINE_STEP = {"kg": 2.5, "lbs": 5.0}
# An estimated one-rep max is the weight divided by the factor for the reps done (F-46).
ONE_REP_MAX_FACTORS = {
    1: 1.0,
    2: 0.97,
    3: 0.94,
    4: 0.92,
    5: 0.89,
    6: 0.86,
    7: 0.83,
    8: 0.81,
    9: 0.78,
    10: 0.75,
    11: 0.73,
    12: 0.71,
    13: 0.7,
    14: 0.68,
    15: 0.67,
    16: 0.65,
    17: 0.64,
    18: 0.63,
    19: 0.61,
    20: 0.6,
    21: 0.59,
    22: 0.58,
    23: 0.57,
    24: 0.56,
    25: 0.55,
    26: 0.54,
    27: 0.53,
    28: 0.52,
    29: 0.51,
    30: 0.5,
}
ONE_REP_MAX_FACTOR_PAST_30 = 0.5
# The share of a one-rep max a new exercise starts at, by the rep range it
# must fit inside; the first row that fits wins, and no row means no weight.
STARTING_SHARES = (((4, 6), 0.8), ((10, 12), 0.64), ((8, 12), 0.67), ((12, 15), 0.63))

RepRange = tuple[int, int]
Log = Sequence[dict[str, Any]]  # one session's sets of one exercise: `type`, `reps`, `weight_kg`


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _round2(x: float) -> float:
    return _round_half_up(x * 100) / 100


def _round3(x: float) -> float:
    return _round_half_up(x * 1000) / 1000


def to_kg(weight: float, unit: str) -> float:
    return weight if unit == "kg" else weight / LBS_PER_KG


def in_unit(kg: float, unit: str) -> float:
    """A kilogram value in the exercise's unit, to two decimals."""
    return _round2(kg * LBS_PER_KG if unit == "lbs" else kg)


# The program week (F-41)


def _week_start(day: date, first_weekday: int) -> date:
    sunday_based = (day.weekday() + 1) % 7
    return day - timedelta(days=(sunday_based - first_weekday) % 7)


def week_start(now: datetime, first_weekday: str, zone: tzinfo) -> date:
    """The first day of the week `now` is in, for a user whose weeks start on `first_weekday`."""
    first = WEEKDAYS.index(first_weekday) if first_weekday in WEEKDAYS else WEEKDAYS.index("monday")
    return _week_start(now.astimezone(zone).date(), first)


def program_week(created_at: datetime, now: datetime, first_weekday: str, zone: tzinfo) -> int:
    """Whole weeks from the week the program was made in to the current week, plus one."""
    started = week_start(created_at, first_weekday, zone)
    return (week_start(now, first_weekday, zone) - started).days // 7 + 1


def weeks_in_cycle(deloads: bool) -> int:
    return CYCLE_WEEKS + 1 if deloads else CYCLE_WEEKS


def cycle(week: int, deloads: bool) -> int:
    return (max(1, week) - 1) // weeks_in_cycle(deloads) + 1


def week_of_cycle(week: int, deloads: bool) -> int:
    return (max(1, week) - 1) % weeks_in_cycle(deloads) + 1


def is_deload_week(week: int, deloads: bool) -> bool:
    return week_of_cycle(week, deloads) > CYCLE_WEEKS


# Rounding to equipment the user owns (F-43)


@dataclass(frozen=True)
class Equipment:
    kind: str  # machine, dumbbell or barbell
    unit: str  # lbs or kg
    dumbbells: tuple[float, ...] = ()
    bars: tuple[float, ...] = ()
    plates: tuple[float, ...] = ()


def equipment(kind: str | None, unit: str, available: dict[str, Any]) -> Equipment | None:
    """The equipment an exercise rounds to, or None for a kind Trainer suggests no weight for (F-46a)."""

    def owned(name: str) -> tuple[float, ...]:
        key = f"{name}{'Kg' if unit == 'kg' else 'Lbs'}"
        values = available.get(key)
        return tuple(values if isinstance(values, list) else DEFAULT_WEIGHTS[key])

    if kind == "machine":
        return Equipment("machine", unit)
    if kind == "dumbbell":
        return Equipment("dumbbell", unit, dumbbells=owned("dumbbells"))
    if kind == "barbell":
        return Equipment("barbell", unit, bars=owned("bars"), plates=owned("plates"))
    return None


def _nearest(target: float, options: Sequence[float]) -> float | None:
    """The closest option; of two equally close, the first listed."""
    best = None
    for option in options:
        if best is None or abs(option - target) < abs(best - target):
            best = option
    return best


def _toward(target: float, options: Sequence[float], direction: str, current: float) -> float | None:
    """The target if the user can load it, else the closest step from `current` in that direction."""
    if direction == "none":
        return current
    exact = target if target in options else None
    if direction == "increase":
        between = [w for w in options if current < w < target]
        above = next((w for w in options if w > target), None)
        candidates = (exact, between[-1] if between else None, above)
    else:
        just_above_target = next((w for w in options if target < w < current), None)
        below = next((w for w in reversed(options) if w < target), None)
        candidates = (exact, just_above_target, below)
    return next((c for c in candidates if c is not None), None)


def _barbell_loads(gear: Equipment, limit: float) -> list[float]:
    """Every weight a bar and two equal sides of plates can make, a little past `limit`."""
    ceiling = limit + 2 * max([0.0, *gear.plates])
    bars = [b for b in gear.bars if b > 0] or DEFAULT_WEIGHTS["barsKg" if gear.unit == "kg" else "barsLbs"]
    plates = [p for p in gear.plates if p > 0]
    loads: set[float] = set()
    for bar in bars:
        side_limit = (ceiling - bar) / 2
        sides = {0.0}
        frontier = [0.0]
        while frontier:
            reached = []
            for side in frontier:
                for plate in plates:
                    total = _round3(side + plate)
                    if total <= side_limit and total not in sides:
                        sides.add(total)
                        reached.append(total)
            frontier = reached
        loads.update(_round3(bar + side * 2) for side in sides)
    return sorted(loads)


def loadable(
    target_kg: float, gear: Equipment, direction: str | None = None, current: float | None = None
) -> float | None:
    """The target as a weight the user can actually load, in the equipment's unit, or None.

    With a direction and the current weight, the answer never moves the wrong
    way; without them it is the nearest weight there is.
    """
    target = in_unit(target_kg, gear.unit)
    if gear.kind == "machine":
        steps = target / MACHINE_STEP[gear.unit]
        if direction == "increase":
            return math.ceil(steps) * MACHINE_STEP[gear.unit]
        if direction == "decrease":
            return math.floor(steps) * MACHINE_STEP[gear.unit]
        return _round_half_up(steps) * MACHINE_STEP[gear.unit]
    if gear.kind == "dumbbell":
        if not gear.dumbbells:
            return None
        # A dumbbell exercise is logged as both dumbbells together, so the options are pairs.
        options: Sequence[float] = [w * 2 for w in sorted(gear.dumbbells)]
    else:
        options = _barbell_loads(gear, max(target, current or 0))
    if not direction or current is None:
        return _nearest(target, options)
    return _toward(target, options, direction, current)


# The next weight (F-43, F-44)


@dataclass(frozen=True)
class Prescription:
    """What Trainer prescribes for one exercise. `weight` None means it suggests none."""

    direction: str  # increase, decrease, none, deload, or new
    weight: float | None = None  # in `unit`
    unit: str = "kg"
    warmups: tuple[float, ...] = ()
    rep_range: RepRange | None = None

    @property
    def weight_kg(self) -> float | None:
        return None if self.weight is None else to_kg(self.weight, self.unit)

    @property
    def warmups_kg(self) -> tuple[float, ...]:
        return tuple(to_kg(w, self.unit) for w in self.warmups)


def _working(log: Log) -> list[dict[str, Any]]:
    return [s for s in log if s.get("type") == "normal"]


def _verdict(log: Log, set_count: int, rep_range: RepRange) -> str | None:
    """How the last session went: every working set at or past the top, every one short of the bottom, or neither."""
    sets = _working(log)
    if not sets:
        return None
    if len(sets) < set_count:
        return "none"
    if all((s.get("reps") or 0) >= rep_range[1] for s in sets):
        return "increase"
    if all((s.get("reps") or 0) < rep_range[0] for s in sets):
        return "decrease"
    return "none"


def warmup_count(count: Any) -> int:
    """None, one or two warm-ups, whatever the program says."""
    if isinstance(count, bool) or not isinstance(count, int | float) or not math.isfinite(count) or count <= 0:
        return 0
    return 2 if count >= 2 else 1


def warmups(weight: float | None, count: int, gear: Equipment) -> tuple[float, ...]:
    """One warm-up at 60% of the working weight; two at 40% and 60%; each the nearest weight there is."""
    if not weight:
        return ()
    shares = (loadable(to_kg(weight, gear.unit) * share, gear) for share in WARMUP_SHARES[count])
    return tuple(w for w in shares if w is not None)


def next_weight(
    logs: Sequence[Log], set_count: int, rep_range: RepRange, warmup_sets: int, gear: Equipment, deload: bool
) -> Prescription | None:
    """The weight for an exercise this template has logged before, from its latest session.

    `logs` are the exercise's sets from this template's past sessions, oldest
    first, deload weeks left out. The base is the lightest working set: 5% more
    when every set reached the top of the range, 5% less when every set fell
    short of the bottom, the same otherwise, then rounded to the equipment. In
    a deload week, 60% of that.
    """
    if not logs:
        return None
    verdict = _verdict(logs[-1], set_count, rep_range)
    if verdict is None:
        return None
    base_kg = min(float(s.get("weight_kg") or 0) for s in _working(logs[-1]))
    target_kg = base_kg * {"increase": STEP_UP, "decrease": STEP_DOWN, "none": 1.0}[verdict]
    weight = loadable(target_kg, gear, verdict, in_unit(base_kg, gear.unit))
    if weight is None:
        return None
    if deload:
        weight = loadable(to_kg(weight, gear.unit) * DELOAD_SHARE, gear) or weight
        verdict = "deload"
    return Prescription(verdict, weight, gear.unit, warmups(weight, warmup_sets, gear))


# A new exercise (F-46)


def one_rep_max_kg(weight_kg: float, reps: int) -> float:
    if reps <= 0:
        return 0.0
    return weight_kg / ONE_REP_MAX_FACTORS.get(reps, ONE_REP_MAX_FACTOR_PAST_30)


def starting_weight(
    best_one_rep_max_kg: float | None, rep_range: RepRange, warmup_sets: int, gear: Equipment
) -> Prescription | None:
    """The weight for an exercise this template has never logged: a share of its recent best one-rep max."""
    share = next((s for (low, high), s in STARTING_SHARES if rep_range[0] >= low and rep_range[1] <= high), None)
    if not best_one_rep_max_kg or share is None:
        return None
    weight = loadable(best_one_rep_max_kg * share, gear)
    if weight is None:
        return None
    return Prescription("new", weight, gear.unit, warmups(weight, warmup_sets, gear))


# The next rep range, for exercises logged by reps alone (F-45)


def _rung_up(rep_range: RepRange) -> RepRange | None:
    return next((rung for rung in REP_LADDER if rung[0] >= rep_range[1]), None)


def _rung_down(rep_range: RepRange) -> RepRange | None:
    return next((rung for rung in reversed(REP_LADDER) if rung[0] < rep_range[0]), None)


def next_rep_range(logs: Sequence[Log], set_count: int, base: RepRange, deload: bool) -> Prescription:
    """The rep range for a reps-only exercise: every past session moves it a rung, starting from the program's."""
    rep_range, direction = base, "none"
    for log in logs:
        verdict = _verdict(log, set_count, rep_range)
        if verdict is None:
            continue
        moved = {"increase": _rung_up, "decrease": _rung_down}.get(verdict, lambda r: None)(rep_range)
        direction, rep_range = (verdict, moved) if moved else ("none", rep_range)
    if deload:
        return Prescription("deload", rep_range=_rung_down(rep_range) or rep_range)
    if not logs:
        return Prescription("new", rep_range=base)
    return Prescription(direction, rep_range=rep_range)
