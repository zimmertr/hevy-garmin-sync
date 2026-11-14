"""Every fake the suite uses, and the pinned clock.

The fakes are the preview's (src/hevy_garmin_sync/preview.py), which answer in
the shapes Hevy and Garmin answer in, with every name, id and token made up
(spec D-10). Here each also records what it was asked and can be told to fail
the way the real service fails. tests/test_recorded_shapes.py holds every reply
to tests/data/recorded_shapes.json.
"""

import io
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.request import Request
from zoneinfo import ZoneInfo

import garminconnect

from hevy_garmin_sync import preview
from hevy_garmin_sync.exercises import ExerciseMap, GarminExercise
from hevy_garmin_sync.preview import (
    GARMIN_TOKENS,
    HEVY_SESSION_COOKIE,
    HEVY_SESSION_TOKENS,
    LBS_PER_KG,
    PROGRAM_START,
    FakeResponse,
    garmin_error,
    hevy_deleted_event,
    hevy_exercise,
    hevy_folder,
    hevy_history_set,
    hevy_logged_set,
    hevy_routine,
    hevy_set,
    hevy_template,
    hevy_unit_row,
    hevy_workout_event,
    logged_lower,
    logged_set,
    logged_workout,
    lower_template,
    trainer_exercise,
    trainer_exercise_templates,
    trainer_program,
    trainer_template,
)
from scripts.check_upstream import GARMIN_URL, HEVY_URL

__all__ = [
    "GARMIN_TOKENS",
    "HEVY_SESSION_COOKIE",
    "HEVY_SESSION_TOKENS",
    "LBS_PER_KG",
    "PROGRAM_START",
    "garmin_error",
    "hevy_deleted_event",
    "hevy_exercise",
    "hevy_folder",
    "hevy_history_set",
    "hevy_logged_set",
    "hevy_routine",
    "hevy_set",
    "hevy_template",
    "hevy_unit_row",
    "hevy_workout_event",
    "logged_lower",
    "logged_set",
    "logged_workout",
    "lower_template",
    "trainer_exercise",
    "trainer_exercise_templates",
    "trainer_program",
    "trainer_template",
]

ZONE = ZoneInfo("America/Los_Angeles")
# A winter afternoon, so the zone's abbreviation is PST.
NOW = datetime(2026, 1, 15, 17, 40, tzinfo=ZONE)
TODAY = NOW.date()

# A Friday the Hevy app showed as cycle 2, week 2 of 6, of the program made at PROGRAM_START (spec D-10).
PROGRAM_WEEK_8 = datetime(2026, 11, 6, 18, 0, tzinfo=ZONE)


def garmin_read_rate_limited(headers: dict[str, str] | None = None) -> garminconnect.GarminConnectTooManyRequestsError:
    """What the library raises for a 429 on a read: its own error, raised from the one that holds the reply."""
    error = garminconnect.GarminConnectTooManyRequestsError("Rate limit exceeded: API Error 429")
    error.__cause__ = garmin_error(429, headers=headers)
    return error



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



def rate_limited(retry_after: str) -> FakeResponse:
    """A Hevy 429 that says how long to wait, for `fail`."""
    return FakeResponse(429, {"error": "made up"}, {"Retry-After": retry_after})


Scripted = BaseException | int | str | FakeResponse | None


class FakeGarminApi(preview.FakeGarminApi):
    """The preview's Garmin, which also records each call, and fails or rotates its token when told to.

    Takes and keeps whatever `garminconnect.Garmin` was built with, so a test can patch the library with it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.init_args = args
        self.init_kwargs = kwargs
        self.pushed: list[int] = []
        self.calls: list[str] = []
        self.signed_in = False
        self.bare_schedule_reply = False
        self._failures: dict[str, list[BaseException]] = {}
        self._rotate_on: set[str] = set()

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

    def login(self) -> tuple[None, None]:
        self._enter("login")
        self.signed_in = True
        return None, None

    def push_workout_to_device(self, workout_id: int) -> dict[str, Any]:
        reply = super().push_workout_to_device(workout_id)
        self.pushed.append(workout_id)
        return reply

    def schedule_workout(self, workout_id: int, day: str) -> dict[str, Any]:
        reply = super().schedule_workout(workout_id, day)
        return {} if self.bare_schedule_reply else reply


class _Scripted:
    """Records each request to a Hevy fake, and answers the next ones as `fail` scripted them."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[dict[str, str]] = []
        self.timeouts: list[float | None] = []
        self._failures: list[Scripted] = []

    def fail(self, *failures: Scripted) -> None:
        """Script the next requests, one each: an exception to raise, a status to answer, a body that is
        not JSON, a whole reply, or None to answer normally."""
        self._failures.extend(failures)

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]

    def _enter(
        self, path: str, headers: dict[str, str] | None, sent: dict[str, Any], timeout: float | None
    ) -> FakeResponse | None:
        self.requests.append((path, sent))
        self.headers.append(headers or {})
        self.timeouts.append(timeout)
        if not self._failures:
            return None
        failure = self._failures.pop(0)
        if isinstance(failure, BaseException):
            raise failure
        if isinstance(failure, FakeResponse):
            return failure
        if isinstance(failure, str):
            return FakeResponse(200, failure)
        if failure is not None:
            return FakeResponse(failure, {"error": "made up"})
        return None


class FakeHevyApi(_Scripted, preview.FakeHevyApi):
    """The preview's api.hevyapp.com, recorded and scriptable."""


class FakeHevyPrivateApi(_Scripted, preview.FakeHevyPrivateApi):
    """The preview's Hevy private API, recorded and scriptable."""


def exercise_map(overrides: Mapping[str, GarminExercise] | None = None) -> ExerciseMap:
    """A small map: a few built-ins by id, the fallback rows for everything else, and CUSTOM_EXERCISE_MAP's entries."""
    return ExerciseMap(
        {
            "T-BENCH": GarminExercise("BENCH_PRESS", "BARBELL_BENCH_PRESS"),
            "T-PLANK": GarminExercise("PLANK", "PLANK"),
            "T-ASSIST": GarminExercise("PULL_UP", "BANDED_PULL_UPS"),
            "T-ASSIST-2": GarminExercise("TRICEPS_EXTENSION", "BODY_WEIGHT_DIP"),
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
        overrides,
    )


def garmin_exercise_list() -> dict[str, Any]:
    """A few entries of Garmin's Exercises.json, in its shape: categories, each with its exercises."""
    return {
        "categories": {
            "CORE": {"exercises": {"PLANK": {"primaryMuscles": ["ABS"]}, "CRUNCH": {"primaryMuscles": ["ABS"]}}},
            "BENCH_PRESS": {
                "exercises": {
                    "DUMBBELL_BENCH_PRESS": {"primaryMuscles": ["CHEST"]},
                    "BARBELL_BENCH_PRESS": {"primaryMuscles": ["CHEST"], "secondaryMuscles": ["TRICEPS"]},
                }
            },
        }
    }


def hevy_spec() -> dict[str, Any]:
    """A cut of Hevy's OpenAPI document: two paths, the four enums the copy keeps and one it doesn't."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Hevy API", "version": "0.0.1", "description": "Made up."},
        "paths": {
            "/v1/workouts/events": {"get": {"summary": "Made up."}},
            "/v1/routines": {
                "parameters": [{"name": "page", "in": "query", "schema": {"type": "integer"}}],
                "post": {"summary": "Made up."},
                "get": {"summary": "Made up."},
            },
        },
        "components": {
            "schemas": {
                "CustomExerciseType": {"type": "string", "enum": ["weight_reps", "reps_only"]},
                "EquipmentCategory": {"type": "string", "enum": ["none", "barbell"]},
                "MuscleGroup": {"type": "string", "enum": ["chest", "abdominals"]},
                "PostRoutinesRequestSet": {
                    "type": "object",
                    "properties": {"type": {"type": "string", "enum": ["warmup", "normal"]}},
                },
                "UserInfo": {"type": "object", "properties": {"weight_unit": {"type": "string", "enum": ["kg"]}}},
            }
        },
    }


def hevy_docs_script(spec: dict[str, Any] | None = None) -> str:
    """Hevy's swagger-ui-init.js as swagger-ui-express writes it: the spec inside `var options`, between code."""
    options = json.dumps({"swaggerDoc": hevy_spec() if spec is None else spec, "customOptions": {}}, indent=2)
    return (
        "\nwindow.onload = function() {\n"
        "  var url = window.location.search.match(/url=([^&]+)/);\n"
        f"  var options = {options};\n"
        "  var spec1 = options.swaggerDoc\n"
        "  var ui = SwaggerUIBundle({ spec: spec1, dom_id: '#swagger-ui' })\n"
        "  window.ui = ui\n"
        "}\n"
    )


class FakeUpstream:
    """urllib's `urlopen` over Garmin's exercise list and Hevy's docs script, the two public files
    scripts/check_upstream.py reads."""

    def __init__(self) -> None:
        self.bodies: dict[str, bytes] = {
            GARMIN_URL: json.dumps(garmin_exercise_list()).encode(),
            HEVY_URL: hevy_docs_script().encode(),
        }
        self.requests: list[Request] = []
        self.timeouts: list[float] = []
        self._failures: dict[str, BaseException] = {}

    def fail(self, url: str, error: BaseException) -> None:
        """Make every request for `url` raise this."""
        self._failures[url] = error

    def __call__(self, url: Request, *, timeout: float) -> io.BytesIO:
        self.requests.append(url)
        self.timeouts.append(timeout)
        if url.full_url in self._failures:
            raise self._failures[url.full_url]
        return io.BytesIO(self.bodies[url.full_url])


class FakeRequests:
    """The app's door for a manual sync, answering what it is told to (W-3)."""

    def __init__(self) -> None:
        self.answer: tuple[str, int] = ("started", 0)
        self.asked: list[bool] = []

    def ask(self, force: bool) -> tuple[str, int]:
        self.asked.append(force)
        return self.answer


class FakeLoop:
    """What the server reads from the app: a status, its health, and the door for a manual sync."""

    def __init__(self) -> None:
        self.status: dict[str, Any] = {"version": "1.2.3", "workouts": []}
        self.requests = FakeRequests()
        self.is_alive = True
        self.is_ready = True

    def alive(self) -> bool:
        return self.is_alive

    def ready(self) -> bool:
        return self.is_ready


class FakeSocket:
    """A connection for http.server's handler, in memory: the raw request in, the raw reply out. No network."""

    def __init__(self, request: bytes) -> None:
        self._request = io.BytesIO(request)
        self.reply = b""

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        return self._request

    def sendall(self, data: bytes) -> None:
        self.reply += bytes(data)

    def settimeout(self, timeout: float | None) -> None:
        pass

    def setsockopt(self, *args: Any) -> None:
        pass
