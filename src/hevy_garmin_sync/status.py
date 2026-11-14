"""What the status page and `GET /api/status` show (spec W-2), as one JSON-ready dict.

The loop builds a new one after each pass and at each step of a manual sync,
and swaps it in whole, so the server's thread only ever reads a finished one.
It holds workout names, weights and the Garmin and Hevy workout ids for the
page's links, never a key, token, cookie, username, email or account id (W-9).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .sync import Counts, Report
from .workout import ROUTINE, STATUTE_US, Exercise, LoggedSet, garmin_name

Json = dict[str, Any]

_POUNDS_PER_KG = 2.2046226218


@dataclass(frozen=True)
class Service:
    """One of Hevy, Hevy Trainer and Garmin, as the page's Services panel shows it."""

    name: str
    state: str  # working, waiting, rejected or off
    reason: str = ""  # why it waits, or the fix for a rejected sign-in
    next_try: datetime | None = None


@dataclass(frozen=True)
class Run:
    """The manual sync, if one is asked for (W-3)."""

    state: str = "idle"  # idle, waiting (for Garmin's wait to end) or running
    force: bool = False
    step: str = ""
    done: int = 0
    total: int = 0
    starts: datetime | None = None  # while waiting: when Garmin's wait ends


@dataclass(frozen=True)
class Facts:
    """Everything the loop knows that the page shows."""

    version: str
    zone: str
    started: datetime
    poll_seconds: int
    next_auto_sync: datetime | None
    last_daily_run: datetime | None
    last_counts: Counts | None
    next_daily_run: datetime
    services: Sequence[Service]
    run: Run
    last_manual: datetime | None  # when the last manual sync ended
    last_manual_counts: Counts | None  # None when it failed
    reports: Sequence[Report]
    system: str | None  # Garmin's measurement system, so weights show in the unit Garmin got them in
    settings: Mapping[str, str]
    preview_pr: str | None = None  # W-10
    preview_commit: str | None = None


def build(facts: Facts) -> Json:
    unit = "lb" if facts.system == STATUTE_US else "kg"
    return {
        "version": facts.version,
        # The banner a preview shows (W-10): its pull request, and the commit it runs, short as GitHub shows it.
        "preview": (
            {"pr": facts.preview_pr, "commit": (facts.preview_commit or "")[:7]} if facts.preview_pr else None
        ),
        "time_zone": facts.zone,
        "started": _time(facts.started),
        "poll_seconds": facts.poll_seconds,
        "next_auto_sync": _time(facts.next_auto_sync),
        "last_daily_run": _time(facts.last_daily_run),
        "last_counts": vars(facts.last_counts) if facts.last_counts else None,
        "next_daily_run": _time(facts.next_daily_run),
        "services": [
            {"name": s.name, "state": s.state, "reason": s.reason, "next_try": _time(s.next_try)}
            for s in facts.services
        ],
        "sync": {
            "state": facts.run.state,
            "force": facts.run.force,
            "step": facts.run.step,
            "done": facts.run.done,
            "total": facts.run.total,
            "starts": _time(facts.run.starts),
            "last_ended": _time(facts.last_manual),
            "last_counts": vars(facts.last_manual_counts) if facts.last_manual_counts else None,
        },
        "workouts": [_workout(r, unit, facts.system) for r in facts.reports],
        "settings": dict(facts.settings),
    }


def _time(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment else None


def _day(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _workout(report: Report, unit: str, system: str | None) -> Json:
    plan = report.plan
    return {
        "title": plan.title or plan.name,
        "kind": plan.kind,
        "folder": plan.folder,
        # A routine's page on hevy.com takes its public API id (checked 2026-11-12); Trainer's templates have none.
        "hevy_id": plan.source_id if plan.kind == ROUTINE else None,
        "garmin_id": report.garmin_id,
        "scheduled": _day(report.scheduled),
        "synced": _time(report.synced),
        "refused": report.refused,
        "retry": _time(report.retry),
        "exercises": [_exercise(e, unit, system) for e in plan.exercises],
    }


def _exercise(exercise: Exercise, unit: str, system: str | None) -> Json:
    working = [s for s in exercise.sets if s.kind != "warmup"]
    warmups = [_weight(s.weight_kg, unit) for s in exercise.sets if s.kind == "warmup" and s.weight_kg]
    weights = sorted({w for s in working if (w := _weight(s.weight_kg, unit))}, key=float)
    weight = None
    if weights:
        # A routine can load each set differently: the lightest to the heaviest.
        weight = f"{weights[0]} {unit}" if len(weights) == 1 else f"{weights[0]}–{weights[-1]} {unit}"
    return {
        "hevy": exercise.title,
        "garmin": garmin_name(exercise.category, exercise.name),
        "chosen_by": exercise.chosen_by,
        "sets": sets_text(exercise),
        "rest": rest_text(exercise.rest_seconds),
        "last": last_text(exercise.previous, unit),
        "weight": weight,
        "direction": exercise.direction,
        "warmups": ", ".join(warmups) or None,
        "no_weight": exercise.no_weight,
    }


def _weight(kg: float | None, unit: str) -> str:
    if not kg:
        return ""
    return f"{round(kg * _POUNDS_PER_KG if unit == 'lb' else kg, 1):g}"


def _length(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    if not minutes:
        return f"{rest} s"
    return f"{minutes} min {rest} s" if rest else f"{minutes} min"


def sets_text(exercise: Exercise) -> str | None:
    """The working sets as `3 × 5`, `3 × 8–12`, `3 × 45 s` or `5, 5, 3` (the warm-ups go with the weight)."""
    working = [s for s in exercise.sets if s.kind != "warmup"]
    if not working:
        return None
    each = []
    for s in working:
        if s.rep_range:
            each.append(f"{s.rep_range[0]}–{s.rep_range[1]}")
        elif s.reps:
            each.append(str(s.reps))
        elif s.seconds:
            each.append(_length(s.seconds))
        elif s.meters:
            each.append(f"{s.meters:g} m")
        else:
            each.append("")
    if len(set(each)) == 1:
        return f"{len(working)} × {each[0]}" if each[0] else f"{len(working)} sets"
    return ", ".join(e or "?" for e in each)


def rest_text(seconds: int | None) -> str | None:
    return f"Rest {_length(seconds)}" if seconds else None


def last_text(logged: Sequence[LoggedSet], unit: str) -> str | None:
    """Last time's working sets, compact: `Last 3 × 5 @ 180`, or `Last 12, 11, 10 @ 110` (TJ, 2026-11-12)."""
    sets = [s for s in logged if s.reps or s.seconds or s.meters]
    if not sets:
        return None
    amounts = [str(s.reps) if s.reps else _length(s.seconds) if s.seconds else f"{s.meters:g} m" for s in sets]
    weights = [_weight(s.weight_kg, unit) for s in sets]
    if len(set(weights)) == 1:
        done = f"{len(sets)} × {amounts[0]}" if len(set(amounts)) == 1 else ", ".join(amounts)
        return f"Last {done} @ {weights[0]}" if weights[0] else f"Last {done}"
    return "Last " + ", ".join(f"{w} × {a}" if w else a for w, a in zip(weights, amounts, strict=True))
