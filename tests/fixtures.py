"""Every fake the suite uses, and the pinned clock.

The fakes answer in the shapes Hevy and Garmin answer in, with every name, id
and token made up (spec D-10), and each can be told to fail the way the real
service fails.
"""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import garminconnect

ZONE = ZoneInfo("America/Los_Angeles")
# A winter afternoon, so the zone's abbreviation is PST.
NOW = datetime(2026, 1, 15, 17, 40, tzinfo=ZONE)
TODAY = NOW.date()

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
        return self.entries[entry_id]

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
