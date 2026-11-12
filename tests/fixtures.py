"""Every fake the suite uses, and the pinned clock.

The fakes answer in the shapes Hevy and Garmin answer in, with every name, id
and token made up (spec D-10), and each can be told to fail the way the real
service fails. Every reply follows the shapes in tests/data/recorded_shapes.json,
which tests/test_recorded_shapes.py holds them to: Garmin's and Hevy Trainer's
recorded on 2026-11-10, Hevy's public API's on 2026-11-11, and on 2026-11-11 too
a stored repeat group, a row of the unit list and `user_key_values`.
"""

import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request
from zoneinfo import ZoneInfo

import garminconnect
import requests
from requests.structures import CaseInsensitiveDict

from hevy_garmin_sync.exercises import ExerciseMap, GarminExercise
from hevy_garmin_sync.trainer_rules import DEFAULT_WEIGHTS
from hevy_garmin_sync.workout import step_count
from scripts.check_upstream import GARMIN_URL, HEVY_URL

ZONE = ZoneInfo("America/Los_Angeles")
# A winter afternoon, so the zone's abbreviation is PST.
NOW = datetime(2026, 1, 15, 17, 40, tzinfo=ZONE)
TODAY = NOW.date()

# The Hevy Trainer cases checked against the Hevy app (spec D-10): a program made
# on a Monday, and a Friday the app showed as cycle 2, week 2 of 6.
PROGRAM_START = datetime(2026, 9, 14, 13, 0, tzinfo=ZONE)
PROGRAM_WEEK_8 = datetime(2026, 11, 6, 18, 0, tzinfo=ZONE)

GARMIN_TOKENS = json.dumps({"di_token": "access-1", "di_refresh_token": "refresh-1", "di_client_id": "client"})


def garmin_error(
    status: int, detail: str = "", headers: dict[str, str] | None = None
) -> garminconnect.GarminConnectConnectionError:
    """What python-garminconnect 0.3.20 raises for an HTTP error: the `requests` reply is on `.response`.

    A real `requests.Response`, because one with a 4xx status is falsy.
    """
    error = garminconnect.GarminConnectConnectionError(f"API Error {status}" + (f" - {detail}" if detail else ""))
    reply = requests.Response()
    reply.status_code = status
    reply.headers.update(headers or {})
    error.response = reply
    return error


def garmin_read_rate_limited(headers: dict[str, str] | None = None) -> garminconnect.GarminConnectTooManyRequestsError:
    """What the library raises for a 429 on a read: its own error, raised from the one that holds the reply."""
    error = garminconnect.GarminConnectTooManyRequestsError("Rate limit exceeded: API Error 429")
    error.__cause__ = garmin_error(429, headers=headers)
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


def _filled(defaults: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    """`given` over `defaults`, nested dicts merged too, the way Garmin fills in what a body leaves out.

    The given keys keep their order and come first, so a stored body reads as it was sent.
    """
    merged: dict[str, Any] = {}
    for key, value in given.items():
        base = defaults.get(key)
        merged[key] = _filled(base, value) if isinstance(base, dict) and isinstance(value, dict) else value
    return merged | {key: value for key, value in defaults.items() if key not in merged}


# Garmin's replies, in the shapes recorded on 2026-11-10 (tests/data/recorded_shapes.json), with every value
# made up. tests/test_recorded_shapes.py fails when one drifts.
GARMIN_DATE = "2026-01-15T17:40:00.0"
_GARMIN_STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}
_GARMIN_NO_UNIT = {"unitId": None, "unitKey": None, "factor": None}


def garmin_settings(measurement_system: str | None = "statute_us") -> dict[str, Any]:
    """`get_user_profile`'s reply: the user settings. They hold no time zone (C-7)."""
    number_format = {
        "formatId": 0,
        "formatKey": "made-up",
        "minFraction": 0,
        "maxFraction": 0,
        "groupingUsed": False,
        "displayFormat": None,
    }
    user_data = dict.fromkeys(
        (
            "diveNumber",
            "externalBottomTime",
            "firstbeatCyclingLtTimestamp",
            "firstbeatMaxStressScore",
            "firstbeatRowingLtTimestamp",
            "golfDistanceUnit",
            "golfElevationUnit",
            "golfSpeedUnit",
            "lactateThresholdHeartRateCycling",
            "lactateThresholdHeartRateRowing",
            "lactateThresholdRowingPace",
            "numberDivesAutomatically",
            "trainingStatusPausedDate",
            "virtualCaddieDataSource",
            "wtrPrimaryActivityType",
        )
    ) | {
        "measurementSystem": measurement_system,
        "activityLevel": 5,
        "availableTrainingDays": ["MONDAY"],
        "birthDate": "1990-01-01",
        "firstDayOfWeek": {"dayId": 2, "dayName": "monday", "sortOrder": 2, "isPossibleFirstDay": True},
        "firstbeatRunningLtTimestamp": 1,
        "ftpAutoDetected": False,
        "gender": "made-up",
        "handedness": "RIGHT",
        "heartRateFormat": number_format,
        "height": 180.0,
        "hydrationAutoGoalEnabled": False,
        "hydrationContainers": [{"name": None, "unit": "milliliter", "volume": 500}],
        "hydrationMeasurementUnit": "milliliter",
        "intensityMinutesCalcMethod": "AUTO",
        "lactateThresholdHeartRate": 170,
        "lactateThresholdSpeed": 3.0,
        "moderateIntensityMinutesHrZone": 3,
        "powerFormat": number_format,
        "preferredLongTrainingDays": ["SATURDAY"],
        "thresholdHeartRateAutoDetected": True,
        "timeFormat": "time_twelve_hr",
        "vigorousIntensityMinutesHrZone": 4,
        "weatherLocation": dict.fromkeys(
            ("useFixedLocation", "latitude", "longitude", "locationName", "isoCountryCode", "postalCode")
        ),
        "weight": 80000.0,
        "wheelchairModeEnabled": False,
    }
    return {
        "id": 1,
        "userData": user_data,
        "userSleep": {"sleepTime": 79200, "defaultSleepTime": False, "wakeTime": 21600, "defaultWakeTime": False},
        "userSleepWindows": [
            {
                "sleepWindowFrequency": "DAILY",
                "startSleepTimeSecondsFromMidnight": 79200,
                "endSleepTimeSecondsFromMidnight": 21600,
            }
        ],
        "connectDate": None,
        "sourceType": None,
    }


# What Garmin adds to a workout body it stores, at each level. A repeat group stays a group, its steps inside
# it (recorded 2026-11-11).
_GARMIN_WORKOUT: dict[str, Any] = dict.fromkeys(
    (
        "atpPlanId",
        "consumer",
        "consumerImageURL",
        "consumerName",
        "consumerWebsiteURL",
        "estimateType",
        "estimatedDistanceInMeters",
        "isSessionTransitionEnabled",
        "locale",
        "poolLength",
        "poolLengthUnit",
        "sharedWithUsers",
        "subSportType",
        "trainingPlanId",
        "uploadTimestamp",
        "workoutProvider",
        "workoutSourceId",
        "workoutThumbnailUrl",
    )
) | {
    "author": {
        "userProfilePk": 1,
        "displayName": "made-up",
        "fullName": "Made Up",
        "profileImgNameLarge": None,
        "profileImgNameMedium": "made-up.png",
        "profileImgNameSmall": "made-up.png",
        "userPro": False,
        "vivokidUser": False,
    },
    "avgTrainingSpeed": 0.0,
    "createdDate": GARMIN_DATE,
    "estimatedDistanceUnit": _GARMIN_NO_UNIT,
    "estimatedDurationInSecs": 0,
    "ownerId": 1,
    "shared": False,
    "sportType": _GARMIN_STRENGTH,
    "updatedDate": GARMIN_DATE,
}
_GARMIN_SEGMENT: dict[str, Any] = dict.fromkeys(
    (
        "avgTrainingSpeed",
        "description",
        "estimateType",
        "estimatedDistanceInMeters",
        "estimatedDistanceUnit",
        "estimatedDurationInSecs",
        "poolLength",
        "poolLengthUnit",
    )
) | {"sportType": _GARMIN_STRENGTH}
_GARMIN_STEP: dict[str, Any] = dict.fromkeys(
    (
        "category",
        "childStepId",
        "description",
        "endConditionCompare",
        "endConditionValue",
        "endConditionZone",
        "exerciseName",
        "preferredEndConditionUnit",
        "providerExerciseSourceId",
        "secondaryTargetType",
        "secondaryTargetValueOne",
        "secondaryTargetValueTwo",
        "secondaryTargetValueUnit",
        "secondaryZoneNumber",
        "targetValueOne",
        "targetValueTwo",
        "targetValueUnit",
        "weightUnit",
        "weightValue",
        "workoutProvider",
        "zoneNumber",
    )
) | {
    "equipmentType": {"equipmentTypeId": 0, "equipmentTypeKey": None, "displayOrder": 0},
    "strokeType": {"strokeTypeId": 0, "strokeTypeKey": None, "displayOrder": 0},
}
_GARMIN_GROUP: dict[str, Any] = dict.fromkeys(("endConditionCompare", "preferredEndConditionUnit"))
_GARMIN_LIST_ITEM: dict[str, Any] = dict.fromkeys(
    (
        "atpPlanId",
        "consumer",
        "description",
        "estimateType",
        "estimatedDistanceInMeters",
        "trainingPlanId",
        "workoutId",
        "workoutName",
        "workoutProvider",
        "workoutSourceId",
        "workoutThumbnailUrl",
    )
) | {
    "author": dict.fromkeys(
        (
            "userProfilePk",
            "displayName",
            "fullName",
            "profileImgNameLarge",
            "profileImgNameMedium",
            "profileImgNameSmall",
        )
    )
    | {"userPro": False, "vivokidUser": False},
    "createdDate": GARMIN_DATE,
    "estimated": True,
    "estimatedDistanceUnit": _GARMIN_NO_UNIT,
    "estimatedDurationInSecs": 0,
    "ownerId": 1,
    "poolLength": 0.0,
    "poolLengthUnit": _GARMIN_NO_UNIT,
    "shared": False,
    "sportType": _GARMIN_STRENGTH,
    "updateDate": GARMIN_DATE,
}
_GARMIN_ENTRY: dict[str, Any] = dict.fromkeys(
    (
        "associatedActivityDateTime",
        "associatedActivityId",
        "atpPlanTypeId",
        "consumer",
        "newName",
        "priority",
        "tpType",
    )
) | {"createdDate": "2026-01-15", "itp": False, "nameChanged": False, "ownerId": 1, "protected": False, "race": False}


_GARMIN_LISTED = ("workoutId", "workoutName", "description", "createdDate", "ownerId", "sportType")


class FakeGarminApi:
    """The part of `garminconnect.Garmin` the app calls, over an in-memory account.

    Tests may put a workout or an entry in `workouts` or `entries` with only the
    fields they need; the replies fill in the rest.
    """

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
        # (category, exercise) sent -> the exercise Garmin stores instead. It stored these with an empty
        # exercise name, the first two on 2026-11-10 and `CURL` on 2026-11-11, and every other exercise sent
        # as it was (#22).
        self.renamed: dict[tuple[str, str], str] = {
            ("HYPEREXTENSION", "HYPEREXTENSION"): "",
            ("BATTLE_ROPE", "BATTLE_ROPE"): "",
            ("CURL", "CURL"): "",
        }
        # A workout of more steps than this is refused with `too_many_steps`, should Garmin cap them.
        self.max_steps: int | None = None
        self.too_many_steps: BaseException = garmin_error(400, "made up: the workout has too many steps")
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
        return garmin_settings(self.measurement_system)

    def connectapi(self, path: str) -> dict[str, Any]:
        self._enter("connectapi")
        return {"displayName": "someone", "profileId": 1}

    def get_user_timezone(self) -> str | None:
        self._enter("get_user_timezone")
        return self.zone if self.display_name else None

    def get_workouts(self, start: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        self._enter("get_workouts")
        listed = []
        for w in self.workouts.values():
            # The list's items carry a few of the stored workout's fields, and call `updatedDate` `updateDate`.
            item = {k: w[k] for k in _GARMIN_LISTED if k in w}
            if "updatedDate" in w:
                item["updateDate"] = w["updatedDate"]
            listed.append(_filled(_GARMIN_LIST_ITEM, item))
        return listed[start : start + limit]

    def upload_workout(self, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("upload_workout")
        if self.max_steps is not None and step_count(body) > self.max_steps:
            raise self.too_many_steps
        workout_id = self._new_id()
        self.workouts[workout_id] = self._as_stored(body, workout_id)
        return self.workouts[workout_id]

    def get_workout_by_id(self, workout_id: int) -> dict[str, Any]:
        self._enter("get_workout_by_id")
        if workout_id not in self.workouts:
            raise garmin_error(404)
        return self.workouts[workout_id]

    def _as_stored(self, body: dict[str, Any], workout_id: int) -> dict[str, Any]:
        """The body as Garmin keeps it: its gaps filled, its steps numbered, and no `stepName` (#24)."""
        sent: dict[str, Any] = json.loads(json.dumps(body))
        step_ids = iter(range(1, 10_000))

        def stored_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
            kept: list[dict[str, Any]] = []
            for step in steps:
                if "workoutSteps" in step:
                    group = _filled(_GARMIN_GROUP, step) | {"stepId": next(step_ids)}
                    kept.append(group | {"workoutSteps": stored_steps(step["workoutSteps"])})
                    continue
                step.pop("stepName", None)
                pair = (step.get("category"), step.get("exerciseName"))
                if pair in self.renamed:
                    step["exerciseName"] = self.renamed[pair]
                if isinstance(step.get("weightUnit"), dict):
                    step["weightUnit"] = {"factor": 1.0} | step["weightUnit"]
                kept.append(_filled(_GARMIN_STEP, step) | {"stepId": next(step_ids)})
            return kept

        segments = [
            _filled(_GARMIN_SEGMENT, segment) | {"workoutSteps": stored_steps(segment.get("workoutSteps") or [])}
            for segment in sent.get("workoutSegments") or []
        ]
        created = self.workouts.get(workout_id, {}).get("createdDate", GARMIN_DATE)
        return _filled(_GARMIN_WORKOUT, sent) | {
            "workoutId": workout_id,
            "workoutSegments": segments,
            "createdDate": created,
        }

    def update_workout(self, workout_id: int, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("update_workout")
        if workout_id not in self.workouts:
            raise garmin_error(404)
        self.workouts[workout_id] = self._as_stored(body, workout_id)
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

    def _entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """A calendar entry as Garmin answers it: with its workout whole, but for the author."""
        found = self.workouts.get((entry.get("workout") or {}).get("workoutId"))  # type: ignore[arg-type]
        return _GARMIN_ENTRY | entry | ({"workout": found | {"author": None}} if found else {})

    def get_scheduled_workouts_by_period(self, start: str, end: str) -> list[dict[str, Any]]:
        self._enter("get_scheduled_workouts_by_period")
        return [self._entry(e) for e in self.entries.values() if start <= e["calendarDate"] <= end]

    def schedule_workout(self, workout_id: int, day: str) -> dict[str, Any]:
        self._enter("schedule_workout")
        entry_id = self._new_id()
        self.entries[entry_id] = {
            "workoutScheduleId": entry_id,
            "calendarDate": day,
            "workout": {"workoutId": workout_id},
        }
        return {} if self.bare_schedule_reply else self._entry(self.entries[entry_id])

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
    def __init__(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = CaseInsensitiveDict(headers or {})

    def json(self) -> Any:
        if isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body


def rate_limited(retry_after: str) -> FakeResponse:
    """A Hevy 429 that says how long to wait, for `fail`."""
    return FakeResponse(429, {"error": "made up"}, {"Retry-After": retry_after})


Scripted = BaseException | int | str | FakeResponse | None


# Hevy's public replies, in the shapes recorded on 2026-11-11. A set carries `rep_range` only when it has a
# rep range; the one recorded had none, and tests/test_recorded_shapes.py takes the field as optional.
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
    """An exercise template, in the shape Hevy sent on 2026-11-11."""
    return {
        "id": template_id,
        "title": title,
        "type": "weight_reps",
        "primary_muscle_group": "chest",
        "secondary_muscle_groups": [],
        "equipment": "barbell",
        "is_custom": False,
        "thumbnail_url": "made-up",
    } | fields


def hevy_history_set(
    kilograms: float | None,
    reps: int | None,
    workout_start: str | None,
    set_type: str = "normal",
    template_id: str = "T-BENCH",
    **fields: Any,
) -> dict[str, Any]:
    """One set of an exercise's history, in the shape Hevy sent on 2026-11-11, with `fields` over it."""
    return {
        "weight_kg": None if kilograms is None else float(kilograms),
        "reps": reps,
        "set_type": set_type,
        "workout_start_time": workout_start,
        "workout_end_time": workout_start,
        "workout_id": "made-up",
        "workout_title": "Made Up",
        "exercise_template_id": template_id,
        "rpe": 8,
        "distance_meters": None,
        "duration_seconds": None,
        "custom_metric": None,
    } | fields


def hevy_logged_set(index: int = 0, **fields: Any) -> dict[str, Any]:
    """One set of a workout in a workout event, in the shape Hevy sent on 2026-11-10: 60 kg for 8 at RPE 8."""
    return {
        "index": index,
        "type": "normal",
        "weight_kg": 60.0,
        "reps": 8,
        "rpe": 8,
        "distance_meters": None,
        "duration_seconds": None,
        "custom_metric": None,
    } | fields


def hevy_workout_event(
    workout_id: str,
    template_id: str,
    title: str,
    sets: list[dict[str, Any]] | None = None,
    start: str = "2026-01-15T17:00:00+00:00",
) -> dict[str, Any]:
    """An `updated` workout event, in the shape Hevy sent on 2026-11-10: a logged workout of one exercise,
    with `sets`, else one `hevy_logged_set`."""
    exercise = {
        "index": 0,
        "title": title,
        "notes": None,
        "exercise_template_id": template_id,
        "superset_id": None,
        "sets": [s | {"index": i} for i, s in enumerate(sets or [hevy_logged_set()])],
    }
    return {
        "type": "updated",
        "workout": {
            "id": workout_id,
            "title": "Made Up",
            "routine_id": None,
            "description": "",
            "start_time": start,
            "end_time": start,
            "updated_at": start,
            "created_at": start,
            "exercises": [exercise],
        },
    }


def hevy_deleted_event(workout_id: str) -> dict[str, Any]:
    """A `deleted` workout event: the workout's id alone, as Hevy's API reference gives it."""
    return {"type": "deleted", "id": workout_id, "deleted_at": "2026-01-15T18:00:00+00:00"}


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
        self._failures: list[Scripted] = []

    def fail(self, *failures: Scripted) -> None:
        """Script the next requests, one each: an exception to raise, a status to answer, a body that is
        not JSON, a whole reply, or None to answer normally."""
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
            if isinstance(failure, FakeResponse):
                return failure
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
        "hevy_trainer_program_id": "program-1",
        "key": key,
        "name": key,  # Hevy sent the key as the name on 2026-11-10
        "index": 0,
        "edits": [],
        "exercises": [e | {"index": i} for i, e in enumerate(exercises)],
    } | fields


def trainer_program(templates: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    created = PROGRAM_START.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "id": "program-1",
        "created_at": created,
        "updated_at": created,
        "current_week": 5,  # not the week the Hevy app shows; the app counts from `created_at`
        "deloads_enabled": False,
        # The workout the Hevy app would start next, counted in `index` order (spec F-31).
        "next_workout_index": 0,
        "next_workout_index_updated_at": created,
        "exercises_rotated_at": created,
        "templates": [t | {"index": i} for i, t in enumerate(templates)],
        "cardio_preference": "made-up",
        "equipments": ["dumbbell"],
        "goal": "made-up",
        "level": "made-up",
        "program_variety": "made-up",
        "rest_timer_length": "made-up",
        "schema_version": "made-up",
        "split_type": "made-up",
        "weekly_frequency": 2,
        "workout_duration_minutes": 60,
    } | fields


def hevy_unit_row(template_id: str, unit: str) -> dict[str, Any]:
    """An exercise logged in `unit` ("kg" or "lbs"): a row of `/exercise_template_units`, as sent on 2026-11-11."""
    return {"id": 1, "exercise_template_id": template_id, "weight_unit": unit}


def logged_set(pounds: float | None, reps: int | None, indicator: str = "normal") -> dict[str, Any]:
    """One set of a logged workout as the private API returns it: its type is its `indicator`."""
    return {
        "id": "set-1",
        "index": 0,
        "indicator": indicator,
        "reps": reps,
        "weight_kg": None if pounds is None else pounds / LBS_PER_KG,
        "rpe": 8,
        "completed_at": "2026-01-15T18:00:00Z",
        "distance_meters": None,
        "duration_seconds": None,
        "custom_metric": None,
        "geospatial_data": None,
        "personalRecords": [],
        "prs": [],
        "yearly_prs": [],
    }


def _logged_exercise(template_id: str, sets: list[dict[str, Any]]) -> dict[str, Any]:
    titles = dict.fromkeys(
        (
            "title",
            "ar_title",
            "ca_title",
            "de_title",
            "es_title",
            "fr_title",
            "hi_title",
            "it_title",
            "ja_title",
            "ko_title",
            "pl_title",
            "pt_br_title",
            "pt_title",
            "ru_title",
            "tr_title",
            "zh_cn_title",
            "zh_tw_title",
        ),
        "Made Up",
    )
    return titles | {
        "id": f"logged-{template_id}",
        "exercise_template_id": template_id,
        "sets": [s | {"index": i} for i, s in enumerate(sets)],
        "custom_exercise_image_url": None,
        "equipment_category": "dumbbell",
        "exercise_type": "weight_reps",
        "media_type": "made-up",
        "muscle_group": "made-up",
        "notes": "",
        "other_muscles": ["made-up"],
        "pinned_notes": [],
        "priority": 0,
        "rest_seconds": 90,
        "superset_id": None,
        "thumbnail_url": "made-up",
        "url": "made-up",
        "volume_doubling_enabled": False,
    }


def logged_workout(
    template_id: str | None, start: datetime, sets_by_exercise: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """A logged workout as the private API returns it: its start in Unix seconds, and its Trainer template."""
    when = start.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "id": f"workout-{int(start.timestamp())}",
        "short_id": "made-up",
        "index": 0,
        "nth_workout": 1,
        "name": "Made Up",
        "description": "",
        "trainer_program_id": "program-1",
        "trainer_workout_template_id": template_id,
        "is_trainer_workout": template_id is not None,
        "start_time": int(start.timestamp()),
        "end_time": int(start.timestamp()) + 3600,
        "created_at": when,
        "updated_at": when,
        "estimated_volume_kg": 1000.0,
        "user_id": "made-up",
        "username": "someone",
        "profile_image": "made-up",
        "verified": False,
        "apple_watch": False,
        "wearos_watch": False,
        "include_warmup_sets": False,
        "is_biometrics_public": False,
        "is_liked_by_user": False,
        "is_private": False,
        "show_on_gym_profile": False,
        "like_count": 0,
        "comment_count": 0,
        "comments": [],
        "image_urls": [],
        "like_images": [],
        "media": [],
        "preview_workout_likes": [],
        "gym": {"type": "made-up"},
        "userGym": {"type": "made-up"},
        "user_gym": {"type": "made-up"},
        "exercises": [_logged_exercise(exercise_id, sets) for exercise_id, sets in sets_by_exercise.items()],
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
        self.user: Any = {
            "username": "someone",
            "weight_unit": "lbs",
            "first_weekday": "monday",
            "distance_unit": "miles",
            "body_measurement_unit": "in",
            "default_workout_show_on_gym_profile": False,
            "default_workout_visibility_public": False,
            "inline_set_timer_enabled": False,
            "plate_calculator_enabled": False,
            "rpe_enabled": False,
            "superset_scrolling": False,
            "volume_includes_warmup_sets": False,
            "workout_keep_awake": False,
        }
        # Hevy's defaults, but for the dumbbells of the account the rules were checked against.
        weights = {key: list(values) for key, values in DEFAULT_WEIGHTS.items()} | {
            "dumbbellsLbs": [5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 30, 35, 40, 45, 50]
        }
        self.trainer: Any = {
            "availableWeights": weights,
            "availableEquipment": weights,
            "excludedExercisesIds": ["made-up"],
            "injuries": [],
            "updated_at": "2026-01-15T18:00:00Z",
        }
        # An account that logs no exercise in the other unit; `hevy_unit_row` builds a row for one that does.
        self.units: Any = []
        # Hevy's per-user key and value store; the live check reads it, the app does not. On 2026-11-11 it was a
        # dict of ten interface settings, each a str or a bool.
        self.key_values: Any = {"TimerSound": "made up", "DisableSuggestedUsers": False}
        self.program: dict[str, Any] | None = None
        self.workouts: list[dict[str, Any]] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[dict[str, str]] = []
        self.timeouts: list[float | None] = []
        self._failures: list[Scripted] = []

    def fail(self, *failures: Scripted) -> None:
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
            if isinstance(failure, FakeResponse):
                return failure
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
        if path == "user_key_values" and isinstance(self.key_values, FakeResponse):
            return self.key_values  # a whole reply, such as a refusal
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
            "user_key_values": self.key_values,
        }
        return FakeResponse(200, replies[path]) if path in replies else FakeResponse(404, {"error": "no such path"})


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
