"""Hevy Trainer's program as planned workouts, with the weights the Hevy app would show (spec section 6, F-31, F-33).

The program comes from Hevy's private API without weights; trainer_rules.py
works them out from the user's logged workouts and preferences. What is read
when (F-4): the program on every poll; the preferences and the logged workouts
at startup, at local midnight, and after a workout was saved, edited or
deleted, which app.py learns from the public workout events and passes on with
`logged`. Only the workout the program says is next goes on today's calendar
(F-31, #25).
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import trainer_rules as rules
from .exercises import ExerciseMap
from .hevy import ASSISTED, WEIGHTED_BODYWEIGHT, Hevy
from .hevy_private import HevyPrivate, parse_time
from .previous import Previous
from .sync import Plans
from .trainer_rules import Prescription, RepRange
from .workout import TRAINER, Exercise, Set, Workout

log = logging.getLogger(__name__)

Json = dict[str, Any]
_FREQUENCY = re.compile(r"^\d+x$")
_WEIGHT_TYPES = ("weight_reps", *WEIGHTED_BODYWEIGHT)
_ONE_REP_MAX_WINDOWS_DAYS = (91, 365)  # the last 3 months, else the last 12 (F-46)
# How a prescription compares with the last session, in the words the log uses.
_DIRECTIONS = {
    "increase": "up",
    "decrease": "down",
    "none": "no change",
    "deload": "deload week",
    "new": "new exercise",
}


def template_name(template: Json) -> str:
    """The template's name; from its key when Hevy sends none ('full_body_3x_b' is 'Full Body').

    Hevy sent the key as the name too on 2026-11-10 ('upper_2x_a'), so a name in a key's form is
    read as a key.
    """
    name, key = str(template.get("name") or ""), str(template.get("key") or "")
    if name and not any(_FREQUENCY.match(token) for token in name.split("_")):
        return name
    words = []
    for token in (key or name).split("_"):
        if _FREQUENCY.match(token):
            break
        words.append(token.capitalize())
    return " ".join(words) or key or name or "Workout"


def shape(value: Any) -> Any:
    """A reply's keys and types with every value left out, safe to log."""
    if isinstance(value, dict):
        return {str(key): shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def _units(reply: Any) -> dict[str, str]:
    """Per-exercise unit overrides from a reply whose shape is not yet known (U-15): read what fits, skip the rest."""
    rows = reply
    if isinstance(reply, dict):
        rows = next((v for v in reply.values() if isinstance(v, list)), [])
    found = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            unit = row.get("weight_unit") or row.get("unit")
            if row.get("exercise_template_id") and unit in ("kg", "lbs"):
                found[str(row["exercise_template_id"])] = unit
    return found


class Trainer:
    def __init__(
        self,
        private: HevyPrivate,
        public: Hevy,
        exercises: ExerciseMap,
        now: Callable[[], datetime],  # the current time in the user's zone
        previous: Previous | None = None,  # None: ENABLE_PREVIOUS_VALUES is false
    ) -> None:
        self._private = private
        self._public = public
        self._exercises = exercises
        self._now = now
        self._previous = previous
        self._read_on: date | None = None
        self._logged_since_read = False
        self._units_shape_said = False
        self._user: Json = {}
        self._available: Json = {}
        self._overrides: dict[str, str] = {}
        self._workouts: list[Json] = []
        self._workouts_since: datetime | None = None
        self._best: dict[str, float | None] = {}
        self._said: dict[str, str] = {}
        self._no_program_said = False
        self._no_next_said = False

    @property
    def private_calls(self) -> int:
        """How many calls Hevy's private API has had, for the per-poll DEBUG line."""
        return self._private.calls

    def check(self) -> None:
        """At startup: one call with the session, so a rejected one shows before the loop (section 11)."""
        self._private.user_preferences()

    def logged(self) -> None:
        """A workout was saved, edited or deleted. Kept until the workouts are read again, so a failure
        in between, or Trainer's own wait after one, does not lose it."""
        self._logged_since_read = True

    def plans(self) -> Plans:
        now = self._now()
        program = self._private.program()
        if program is None:
            if not self._no_program_said:
                self._no_program_said = True
                log.info("This Hevy account has no Hevy Trainer program; syncing routines only")
            return Plans(TRAINER, ())
        self._no_program_said = False

        created = parse_time(program.get("created_at")) or now
        if self._logged_since_read or self._read_on != now.date() or self._workouts_since != created:
            self._read_inputs(created)
            self._read_on = now.date()
            self._logged_since_read = False

        zone = now.tzinfo or UTC
        first_weekday = str(self._user.get("first_weekday") or "monday")
        deloads = bool(program.get("deloads_enabled"))

        def week_of(moment: datetime) -> int:
            return rules.program_week(created, moment, first_weekday, zone)

        week = week_of(now)
        label = f"(C{rules.cycle(week, deloads)}-W{rules.week_of_cycle(week, deloads)})"
        deload = rules.is_deload_week(week, deloads)
        this_week = rules.week_start(now, first_weekday, zone)

        workouts = []
        done = set()
        templates = sorted(program.get("templates") or [], key=lambda t: t.get("index") or 0)
        for template in templates:
            template_id = str(template.get("id") or "")
            if not template_id:
                continue
            # This template's logged sessions, each with its start, oldest first.
            sessions = sorted(
                (
                    (started, logged)
                    for logged in self._workouts
                    if logged.get("trainer_workout_template_id") == template_id
                    and (started := parse_time(logged.get("start_time"))) is not None
                ),
                key=lambda session: session[0],
            )
            if any(started.astimezone(zone).date() >= this_week for started, _ in sessions):
                done.add(template_id)  # logged this week: the calendar rule when Hevy names no next workout (F-33)
            history = [logged for started, logged in sessions if not rules.is_deload_week(week_of(started), deloads)]
            exercises = tuple(
                self._exercise(template_id, planned, history, deload, now)
                for planned in sorted(template.get("exercises") or [], key=lambda e: e.get("index") or 0)
            )
            title = f"{template_name(template)} {label}"
            workouts.append(Workout(TRAINER, template_id, f"Hevy/Trainer: {title}", exercises, title=title))
        return Plans(TRAINER, workouts, off_calendar=self._off_calendar(program, templates, workouts, done))

    def _off_calendar(
        self, program: Json, templates: list[Json], workouts: list[Workout], done: set[str]
    ) -> frozenset[str]:
        """Every workout but the one Hevy would start next (F-31, #25).

        `next_workout_index` counts the templates in their `index` order. When
        it names no workout, the week's logged workouts are off instead (F-33),
        so the calendar still shows what is left to do.
        """
        if not workouts:
            return frozenset()
        index = program.get("next_workout_index")
        chosen = ""
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(templates):
            chosen = str(templates[index].get("id") or "")
        if not chosen:
            if not self._no_next_said:
                self._no_next_said = True
                log.warning(
                    "Hevy's program names no next workout (next_workout_index %r), so every Hevy Trainer "
                    "workout not logged this week stays on today's calendar",
                    index,
                )
            return frozenset(done)
        self._no_next_said = False
        return frozenset(w.source_id for w in workouts if w.source_id != chosen)

    def _read_inputs(self, program_created: datetime) -> None:
        self._user = self._private.user_preferences()
        self._available = self._private.trainer_preferences().get("availableWeights") or {}
        overrides = self._private.unit_overrides()
        if not self._units_shape_said:
            self._units_shape_said = True
            log.info("Hevy's per-exercise units reply has this shape (values left out): %s", shape(overrides))
        self._overrides = _units(overrides)
        self._workouts = self._private.workouts_since(str(self._user.get("username") or ""), program_created)
        self._workouts_since = program_created
        self._best = {}

    def _exercise(self, template_id: str, planned: Json, history: list[Json], deload: bool, now: datetime) -> Exercise:
        exercise_id = str(planned.get("exercise_template_id") or "")
        details = self._public.template(exercise_id) or {}
        title = str(details.get("title") or planned.get("title") or exercise_id)
        garmin = self._exercises.find(exercise_id, title, lambda: details)
        bounds = planned.get("rep_range") or {}
        rep_range: RepRange | None = None
        if bounds.get("start") and bounds.get("end"):
            rep_range = (int(bounds["start"]), int(bounds["end"]))

        prescription, why_not = self._prescribe(exercise_id, details, planned, rep_range, history, deload, now)
        self._say(template_id, exercise_id, title, prescription, why_not)
        if prescription and prescription.rep_range:
            rep_range = prescription.rep_range
        weight_kg = prescription.weight_kg if prescription else None
        warmups_kg = prescription.warmups_kg if prescription else ()

        warmup_sets = [
            # The Hevy app gives a warm-up the working sets' rep range too (TJ, 2026-11-13).
            Set(kind="warmup", rep_range=rep_range, weight_kg=warmups_kg[i] if i < len(warmups_kg) else None)
            for i in range(int(planned.get("warmup_set_count") or 0))
        ]
        working = Set(rep_range=rep_range, weight_kg=weight_kg)
        rest = planned.get("rest_seconds")
        return Exercise(
            title=title,
            category=garmin.category,
            name=garmin.name,
            sets=(*warmup_sets, *[working] * int(planned.get("set_count") or 0)),
            rest_seconds=int(rest) if rest else None,
            assisted=details.get("type") in ASSISTED,
            previous=self._previous.sets(exercise_id) if self._previous else (),
            chosen_by=garmin.chosen_by,
            direction=_DIRECTIONS.get(prescription.direction) if prescription else None,
            no_weight=None if prescription else why_not,
        )

    def _prescribe(
        self,
        exercise_id: str,
        details: Json,
        planned: Json,
        rep_range: RepRange | None,
        history: list[Json],
        deload: bool,
        now: datetime,
    ) -> tuple[Prescription | None, str]:
        """Trainer's prescription for one exercise, or None and the reason there is none (F-46a)."""
        if planned.get("kind") != "resistance" or rep_range is None:
            return None, "Trainer plans no weight or rep range for it"
        kind = details.get("type")
        set_count = int(planned.get("set_count") or 0)
        logs = []
        for logged in history:
            done = next(
                (e for e in logged.get("exercises") or [] if e.get("exercise_template_id") == exercise_id), None
            )
            if done is not None:
                logs.append(
                    [
                        # The private API calls a set's type its `indicator`.
                        {
                            "type": s.get("indicator") or s.get("type"),
                            "reps": s.get("reps"),
                            "weight_kg": s.get("weight_kg"),
                        }
                        for s in done.get("sets") or []
                    ]
                )
        if kind == "reps_only":
            return rules.next_rep_range(logs, set_count, rep_range, deload), ""
        unit = self._overrides.get(exercise_id) or ("lbs" if self._user.get("weight_unit") == "lbs" else "kg")
        gear = rules.equipment(details.get("equipment"), unit, self._available)
        if kind not in _WEIGHT_TYPES or gear is None:
            what = f"a {kind or 'unknown'} exercise on {details.get('equipment') or 'unknown'} equipment"
            return None, f"Trainer suggests no weight for {what}"
        warmups = rules.warmup_count(planned.get("warmup_set_count"))
        if logs:
            found = rules.next_weight(logs, set_count, rep_range, warmups, gear, deload)
            return found, "" if found else "its last session has no working set, or no weight the equipment can load"
        if kind != "weight_reps":
            return None, "it has not been logged in this workout yet"
        found = rules.starting_weight(self._best_one_rep_max(exercise_id, now), rep_range, warmups, gear)
        return found, "" if found else "it is new to this workout and nothing gives it a starting weight"

    def _best_one_rep_max(self, exercise_id: str, now: datetime) -> float | None:
        """The best estimated one-rep max over the last 3 months, else the last 12, in kilograms (F-46).

        One call to the public exercise history per exercise, kept until the
        next logged workout.
        """
        if exercise_id not in self._best:
            longest = timedelta(days=max(_ONE_REP_MAX_WINDOWS_DAYS))
            history = self._public.exercise_history(exercise_id, now - longest, now)
            best = None
            for days in _ONE_REP_MAX_WINDOWS_DAYS:
                since = now - timedelta(days=days)
                estimates = [
                    rules.one_rep_max_kg(float(s.get("weight_kg") or 0), int(s.get("reps") or 0))
                    for s in history
                    if s.get("set_type") != "warmup" and (parse_time(s.get("workout_start_time")) or since) >= since
                ]
                best = max(estimates, default=0.0) or None
                if best:
                    break
            self._best[exercise_id] = best
        return self._best[exercise_id]

    def _say(self, template_id: str, exercise_id: str, title: str, found: Prescription | None, why_not: str) -> None:
        """Log each exercise's prescription at INFO when it is first worked out and whenever it changes (O-3)."""
        if found is None:
            text = f"no prescription ({why_not})"
        elif found.rep_range:
            text = f"{found.rep_range[0]}-{found.rep_range[1]} reps ({_DIRECTIONS[found.direction]})"
        else:
            text = f"{found.weight:g} {found.unit} ({_DIRECTIONS[found.direction]})"
            if found.warmups:
                text += ", warm-ups " + ", ".join(f"{w:g}" for w in found.warmups)
        key = f"{template_id}/{exercise_id}"
        if self._said.get(key) != text:
            self._said[key] = text
            log.info("Hevy Trainer: %s: %s", title, text)
