"""Every fake the suite uses, and the pinned clock.

The fakes answer in the shapes Hevy and Garmin answer in, with every name, id
and token made up (spec D-10), and each can be told to fail the way the real
service fails.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import garminconnect

from hevy_garmin_sync.exercises import ExerciseMap, GarminExercise

ZONE = ZoneInfo("America/Los_Angeles")
# A winter afternoon, so the zone's abbreviation is PST.
NOW = datetime(2026, 1, 15, 17, 40, tzinfo=ZONE)
TODAY = NOW.date()

# The Hevy Trainer cases checked against the Hevy app (spec D-10): a program made
# on a Monday, and a Friday the app showed as cycle 2, week 2 of 6.
PROGRAM_START = datetime(2026, 9, 14, 13, 0, tzinfo=ZONE)
PROGRAM_WEEK_8 = datetime(2026, 11, 6, 18, 0, tzinfo=ZONE)

GARMIN_TOKENS = json.dumps({"di_token": "access-1", "di_refresh_token": "refresh-1", "di_client_id": "client"})


def garmin_error(status: int, detail: str = "") -> garminconnect.GarminConnectConnectionError:
    """What python-garminconnect raises for an HTTP error: the status is on `.response`."""
    error = garminconnect.GarminConnectConnectionError(f"API Error {status}" + (f" - {detail}" if detail else ""))
    error.response = SimpleNamespace(status_code=status)
    return error


class FakeGarminTokens:
    """The library's token holder: `dumps`, and `load` from the file it then keeps rewriting."""

    def __init__(self) -> None:
        self.tokens = GARMIN_TOKENS
        self.loaded_from: str | None = None

    def dumps(self) -> str:
        return self.tokens

    def load(self, path: str) -> None:
        text = Path(path).read_text(encoding="utf-8")
        if "di_token" not in text:
            raise garminconnect.GarminConnectConnectionError("Token path not loading cleanly")
        self.loaded_from = path
        self.tokens = text

    def rotate(self) -> None:
        """Garmin handed out a new refresh token in the middle of a call."""
        self.tokens = json.dumps({"di_token": "access-2", "di_refresh_token": "refresh-2", "di_client_id": "client"})


class FakeGarminApi:
    """The part of `garminconnect.Garmin` the app calls, over an in-memory account."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.client = FakeGarminTokens()
        self.display_name: str | None = None
        self.measurement_system: str | None = "statute_us"
        self.zone: str | None = "America/Los_Angeles"
        self.workouts: dict[int, dict[str, Any]] = {}
        self.entries: dict[int, dict[str, Any]] = {}
        self.pushed: list[int] = []
        self.calls: list[str] = []
        self.signed_in = False
        self.bare_schedule_reply = False
        self._failures: dict[str, list[BaseException]] = {}
        self._rotate_on: set[str] = set()
        self._next_id = 1000

    def fail(self, method: str, *errors: BaseException) -> None:
        """Make the next calls to `method` raise these, one each."""
        self._failures.setdefault(method, []).extend(errors)

    def rotate_token_on(self, method: str) -> None:
        self._rotate_on.add(method)

    def _enter(self, method: str) -> None:
        self.calls.append(method)
        if method in self._rotate_on:
            self._rotate_on.discard(method)
            self.client.rotate()
        if self._failures.get(method):
            raise self._failures[method].pop(0)

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def login(self) -> tuple[None, None]:
        self._enter("login")
        self.signed_in = True
        return None, None

    def get_user_profile(self) -> dict[str, Any]:
        self._enter("get_user_profile")
        return {"id": 1, "userData": {"measurementSystem": self.measurement_system}}

    def connectapi(self, path: str) -> dict[str, Any]:
        self._enter("connectapi")
        return {"displayName": "someone", "profileId": 1}

    def get_user_timezone(self) -> str | None:
        self._enter("get_user_timezone")
        return self.zone if self.display_name else None

    def get_workouts(self, start: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        self._enter("get_workouts")
        listed = [
            {k: w.get(k) for k in ("workoutId", "workoutName", "description", "updateDate")}
            for w in self.workouts.values()
        ]
        return listed[start : start + limit]

    def upload_workout(self, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("upload_workout")
        workout_id = self._new_id()
        self.workouts[workout_id] = body | {"workoutId": workout_id}
        return self.workouts[workout_id]

    def update_workout(self, workout_id: int, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("update_workout")
        if workout_id not in self.workouts:
            raise garmin_error(404)
        self.workouts[workout_id] = body | {"workoutId": workout_id}
        return self.workouts[workout_id]

    def delete_workout(self, workout_id: int) -> dict[str, Any]:
        self._enter("delete_workout")
        if workout_id not in self.workouts:
            raise garmin_error(404)
        del self.workouts[workout_id]
        self.entries = {k: e for k, e in self.entries.items() if e["workout"]["workoutId"] != workout_id}
        return {}

    def push_workout_to_device(self, workout_id: int) -> dict[str, Any]:
        self._enter("push_workout_to_device")
        self.pushed.append(workout_id)
        return {}

    def get_scheduled_workouts_by_period(self, start: str, end: str) -> list[dict[str, Any]]:
        self._enter("get_scheduled_workouts_by_period")
        return [e for e in self.entries.values() if start <= e["calendarDate"] <= end]

    def schedule_workout(self, workout_id: int, day: str) -> dict[str, Any]:
        self._enter("schedule_workout")
        entry_id = self._new_id()
        self.entries[entry_id] = {
            "workoutScheduleId": entry_id,
            "calendarDate": day,
            "workout": {"workoutId": workout_id},
            "associatedActivityId": None,
            "associatedActivityDateTime": None,
        }
        return {} if self.bare_schedule_reply else self.entries[entry_id]

    def unschedule_workout(self, entry_id: int) -> dict[str, Any]:
        self._enter("unschedule_workout")
        if entry_id not in self.entries:
            raise garmin_error(404)
        del self.entries[entry_id]
        return {}


class FakeClock:
    """A monotonic clock that only moves when something sleeps on it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self) -> Any:
        if isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body


def hevy_folder(folder_id: int, title: str) -> dict[str, Any]:
    return {"id": folder_id, "index": 0, "title": title, "updated_at": "", "created_at": ""}


def hevy_set(index: int = 0, **fields: Any) -> dict[str, Any]:
    return {
        "index": index,
        "type": "normal",
        "weight_kg": None,
        "reps": None,
        "rep_range": None,
        "distance_meters": None,
        "duration_seconds": None,
        "custom_metric": None,
    } | fields


def hevy_exercise(template_id: str, title: str, sets: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "index": 0,
        "title": title,
        "rest_seconds": 60,
        "notes": None,
        "exercise_template_id": template_id,
        "superset_id": None,
        "sets": [s | {"index": i} for i, s in enumerate(sets)],
    } | fields


def hevy_routine(
    routine_id: str, title: str, folder_id: int | None = None, exercises: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if exercises is None:
        exercises = [hevy_exercise("T-BENCH", "Bench Press (Barbell)", [hevy_set(reps=8, weight_kg=60)] * 3)]
    return {
        "id": routine_id,
        "title": title,
        "folder_id": folder_id,
        "updated_at": "",
        "created_at": "",
        "exercises": [e | {"index": i} for i, e in enumerate(exercises)],
    }


def hevy_template(template_id: str, title: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": template_id,
        "title": title,
        "type": "weight_reps",
        "primary_muscle_group": "chest",
        "secondary_muscle_groups": [],
        "equipment": "barbell",
        "is_custom": False,
    } | fields


class FakeHevyApi:
    """api.hevyapp.com as a `requests.Session`: the public API's lists, paged as Hevy pages them."""

    def __init__(self) -> None:
        self.folders: list[dict[str, Any]] = []
        self.routines: list[dict[str, Any]] = []
        self.templates: list[dict[str, Any]] = [
            hevy_template("T-BENCH", "Bench Press (Barbell)"),
            hevy_template("T-PLANK", "Plank", type="duration", primary_muscle_group="abdominals", equipment="none"),
        ]
        self.events: list[dict[str, Any]] = []
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[dict[str, str]] = []
        self.timeouts: list[float | None] = []
        self._failures: list[BaseException | int | str | None] = []

    def fail(self, *failures: BaseException | int | str | None) -> None:
        """Script the next requests, one each: an exception to raise, a status to answer, a body that is
        not JSON, or None to answer normally."""
        self._failures.extend(failures)

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        path = url.removeprefix("https://api.hevyapp.com/v1")
        params = params or {}
        self.requests.append((path, params))
        self.headers.append(headers or {})
        self.timeouts.append(timeout)
        if self._failures:
            failure = self._failures.pop(0)
            if isinstance(failure, BaseException):
                raise failure
            if isinstance(failure, str):
                return FakeResponse(200, failure)
            if failure is not None:
                return FakeResponse(failure, {"error": "made up"})
        lists = {
            "/routine_folders": ("routine_folders", self.folders),
            "/routines": ("routines", self.routines),
            "/exercise_templates": ("exercise_templates", self.templates),
            "/workouts/events": ("events", self.events),
        }
        if path in lists:
            key, items = lists[path]
            page, size = int(params["page"]), int(params["pageSize"])
            return FakeResponse(
                200,
                {
                    "page": page,
                    "page_count": max(1, -(-len(items) // size)),
                    key: items[(page - 1) * size : page * size],
                },
            )
        if path.startswith("/exercise_templates/"):
            found = [t for t in self.templates if t["id"] == path.rsplit("/", 1)[1]]
            return FakeResponse(200, found[0]) if found else FakeResponse(404, {"error": "not found"})
        if path.startswith("/exercise_history/"):
            return FakeResponse(200, {"exercise_history": self.history.get(path.rsplit("/", 1)[1], [])})
        return FakeResponse(404, {"error": "no such path"})


HEVY_SESSION_TOKENS = {
    "access_token": "hevy-access-1",
    "refresh_token": "hevy-refresh-1",
    "expires_at": "2999-01-01T00:00:00.000Z",
}
# The hevy.com `auth2.0-token` cookie as a browser shows it: the tokens as URL-encoded JSON.
HEVY_SESSION_COOKIE = quote(json.dumps(HEVY_SESSION_TOKENS))
LBS_PER_KG = 2.20462


def trainer_exercise(
    template_id: str, sets: int = 3, warmups: int = 0, rep_range: tuple[int, int] | None = (10, 12), **fields: Any
) -> dict[str, Any]:
    return {
        "id": f"program-{template_id}",
        "index": 0,
        "kind": "resistance",
        "exercise_template_id": template_id,
        "set_count": sets,
        "warmup_set_count": warmups,
        "rep_range": {"start": rep_range[0], "end": rep_range[1]} if rep_range else None,
        "rest_seconds": 90,
    } | fields


def trainer_template(template_id: str, key: str, exercises: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "id": template_id,
        "key": key,
        "name": None,
        "index": 0,
        "edits": [],
        "exercises": [e | {"index": i} for i, e in enumerate(exercises)],
    } | fields


def trainer_program(templates: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "id": "program-1",
        "created_at": PROGRAM_START.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "current_week": 5,  # not the week the Hevy app shows; the app counts from `created_at`
        "deloads_enabled": False,
        "templates": [t | {"index": i} for i, t in enumerate(templates)],
    } | fields


def logged_set(pounds: float | None, reps: int | None, indicator: str = "normal") -> dict[str, Any]:
    """One set of a logged workout as the private API returns it: its type is its `indicator`."""
    return {"indicator": indicator, "reps": reps, "weight_kg": None if pounds is None else pounds / LBS_PER_KG}


def logged_workout(
    template_id: str | None, start: datetime, sets_by_exercise: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """A logged workout as the private API returns it: its start in Unix seconds, and its Trainer template."""
    return {
        "id": f"workout-{int(start.timestamp())}",
        "trainer_workout_template_id": template_id,
        "start_time": int(start.timestamp()),
        "exercises": [
            {"exercise_template_id": exercise_id, "sets": sets} for exercise_id, sets in sets_by_exercise.items()
        ],
    }


def trainer_exercise_templates() -> list[dict[str, Any]]:
    """The public API's templates for the exercises of `lower_template`."""
    return [
        hevy_template("T-GOBLET", "Goblet Squat", equipment="dumbbell", primary_muscle_group="quadriceps"),
        hevy_template("T-LUNGE", "Walking Lunge (Dumbbell)", type="short_distance_weight", equipment="dumbbell"),
        hevy_template("T-LEG-RAISE", "Lying Leg Raise", type="reps_only", equipment="none"),
        hevy_template("T-SIDE-BEND", "Side Bend (Dumbbell)", equipment="dumbbell"),
    ]


def lower_template() -> dict[str, Any]:
    """The Lower workout of the program the rules were checked against (spec section 6)."""
    return trainer_template(
        "t-lower",
        "lower_2x_a",
        [
            trainer_exercise("T-GOBLET", warmups=2, rep_range=(4, 6)),
            trainer_exercise("T-LUNGE"),
            trainer_exercise("T-LEG-RAISE"),
            trainer_exercise("T-SIDE-BEND"),
        ],
    )


def logged_lower(start: datetime) -> dict[str, Any]:
    """A session of that Lower, shaped like the one checked against the Hevy app: afterwards the app
    showed Side Bend up from 35 to 40 lb, Lying Leg Raise up a rep range, and Goblet Squat still at
    80 lb with warm-ups of 30 and 50."""
    return logged_workout(
        "t-lower",
        start,
        {
            "T-GOBLET": [logged_set(30, 6, "warmup"), logged_set(50, 4, "warmup"), *[logged_set(80, 4)] * 3],
            "T-LUNGE": [logged_set(25, None)] * 3,
            "T-LEG-RAISE": [logged_set(None, 15)] * 3,
            "T-SIDE-BEND": [logged_set(35, 15), logged_set(35, 12), logged_set(35, 12)],
        },
    )


class FakeHevyPrivateApi:
    """Hevy's private API as a `requests.Session`: the session refresh and the five reads Trainer needs.

    A bearer other than the current access token gets a 401, and every refresh
    hands out a new pair and kills the old refresh token, as Hevy does.
    """

    def __init__(self) -> None:
        self.access = "hevy-access-1"
        self.refresh = "hevy-refresh-1"
        self.generation = 1
        self.refresh_reply: dict[str, Any] | None = None
        self.user: Any = {"username": "someone", "weight_unit": "lbs", "first_weekday": "monday"}
        self.trainer: Any = {
            "availableWeights": {"dumbbellsLbs": [5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 30, 35, 40, 45, 50]}
        }
        self.units: Any = []
        self.program: dict[str, Any] | None = None
        self.workouts: list[dict[str, Any]] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[dict[str, str]] = []
        self.timeouts: list[float | None] = []
        self._failures: list[BaseException | int | str | None] = []

    def fail(self, *failures: BaseException | int | str | None) -> None:
        """Script the next requests, one each, as `FakeHevyApi.fail` does."""
        self._failures.extend(failures)

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]

    def _enter(
        self, url: str, headers: dict[str, str] | None, sent: dict[str, Any] | None, timeout: float | None
    ) -> FakeResponse | None:
        self.requests.append((url.removeprefix("https://api.hevyapp.com/"), sent or {}))
        self.headers.append(headers or {})
        self.timeouts.append(timeout)
        if self._failures:
            failure = self._failures.pop(0)
            if isinstance(failure, BaseException):
                raise failure
            if isinstance(failure, str):
                return FakeResponse(200, failure)
            if failure is not None:
                return FakeResponse(failure, {"error": "made up"})
        return None

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        scripted = self._enter(url, headers, json, timeout)
        if scripted:
            return scripted
        if "Authorization" not in (headers or {}):
            return FakeResponse(400, "Bad Request")
        if (json or {}).get("refresh_token") != self.refresh:
            return FakeResponse(401, {"error": "made up"})
        self.generation += 1
        self.access = f"hevy-access-{self.generation}"
        self.refresh = f"hevy-refresh-{self.generation}"
        if self.refresh_reply is not None:
            return FakeResponse(200, self.refresh_reply)
        return FakeResponse(
            200,
            {"access_token": self.access, "refresh_token": self.refresh, "expires_at": "2999-01-01T00:00:00.000Z"},
        )

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        scripted = self._enter(url, headers, params, timeout)
        if scripted:
            return scripted
        if (headers or {}).get("Authorization") != f"Bearer {self.access}":
            return FakeResponse(401, {"error": "made up"})
        path = self.requests[-1][0]
        if path == "user_workouts_paged":
            limit, offset = int((params or {})["limit"]), int((params or {})["offset"])
            if limit not in (1, 3):
                return FakeResponse(400, "")
            newest_first = sorted(self.workouts, key=lambda w: w.get("start_time") or 0, reverse=True)
            return FakeResponse(200, {"workouts": newest_first[offset : offset + limit]})
        replies = {
            "v2/user_preferences": self.user,
            "hevy_trainer/user_preferences": self.trainer,
            "exercise_template_units": self.units,
            "hevy_trainer/v3/program": {"program": self.program, "status": "made up"},
        }
        return FakeResponse(200, replies[path]) if path in replies else FakeResponse(404, {"error": "no such path"})


def exercise_map() -> ExerciseMap:
    """A small map: a few built-ins by id, and the fallback rows for everything else."""
    return ExerciseMap(
        {
            "T-BENCH": GarminExercise("BENCH_PRESS", "BARBELL_BENCH_PRESS"),
            "T-PLANK": GarminExercise("PLANK", "PLANK"),
            "T-ASSIST": GarminExercise("PULL_UP", "BANDED_PULL_UPS"),
            "T-SIDE-BEND": GarminExercise("CORE", "SIDE_BEND"),
            "T-GOBLET": GarminExercise("SQUAT", "GOBLET_SQUAT"),
            "T-LEG-RAISE": GarminExercise("LEG_RAISE", "LYING_STRAIGHT_LEG_RAISE"),
            "T-LUNGE": GarminExercise("LUNGE", "DUMBBELL_LUNGE"),
            "T-SWING": GarminExercise("HIP_SWING", "KETTLEBELL_SWING"),
            "T-DIP": GarminExercise("TRICEPS_EXTENSION", "WEIGHTED_DIP"),
        },
        {
            ("biceps", "dumbbell"): GarminExercise("CURL", "DUMBBELL_BICEPS_CURL"),
            ("biceps", "*"): GarminExercise("CURL", "CURL"),
            ("*", "*"): GarminExercise("TOTAL_BODY", "TOTAL_BODY"),
        },
    )
