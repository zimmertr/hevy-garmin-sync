"""Configuration: environment variables only (spec section 11).

Anything wrong here stops the app at startup with a message that names the
variable and the fix, rather than surfacing later as a failed sync.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError
from .exercises import GarminExercise, garmin_exercises

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_MIN_POLL_SECONDS = 10
_GARMIN_LIST = "https://github.com/zimmertr/hevy-garmin-sync/blob/main/src/hevy_garmin_sync/data/garmin_exercises.json"


@dataclass(frozen=True)
class Config:
    hevy_api_key: str
    garmin_token: str | None
    include_folders: tuple[str, ...]
    custom_exercises: Mapping[str, GarminExercise]
    scheduled: bool
    hevy_session: str | None
    poll_seconds: int
    zone: ZoneInfo | None
    data_dir: Path
    log_level: str
    log_format: str

    def summary(self) -> dict[str, str]:
        """The effective configuration for the startup log, secrets redacted (O-3c)."""
        return {
            "HEVY_API_KEY": "set",
            "GARMIN_TOKEN": "set" if self.garmin_token else "unset (using the token in DATA_DIR)",
            "INCLUDE_HEVY_FOLDERS": ", ".join(self.include_folders) or "unset (all routines)",
            # A count only: the entries hold a user's own exercise titles (C-11).
            "CUSTOM_EXERCISE_MAP": (
                f"set ({len(self.custom_exercises)} {'entry' if len(self.custom_exercises) == 1 else 'entries'})"
                if self.custom_exercises
                else "unset (custom exercises go by muscle group and equipment)"
            ),
            "ENABLE_SCHEDULED_WORKOUTS": str(self.scheduled).lower(),
            "HEVY_SESSION": "set (Hevy Trainer on)" if self.hevy_session else "unset (Hevy Trainer off)",
            "HEVY_POLL_INTERVAL_SECONDS": str(self.poll_seconds),
            "TZ": self.zone.key if self.zone else "unset (using the Garmin profile's time zone)",
            "DATA_DIR": str(self.data_dir),
            "LOG_LEVEL": self.log_level,
            "LOG_FORMAT": self.log_format,
        }


def load(env: Mapping[str, str]) -> Config:
    def get(name: str) -> str:
        return env.get(name, "").strip()

    api_key = get("HEVY_API_KEY")
    if not api_key:
        raise ConfigError("HEVY_API_KEY is required: create a key at https://hevy.com/settings?developer (Hevy Pro)")

    scheduled = get("ENABLE_SCHEDULED_WORKOUTS").lower() or "true"
    if scheduled not in ("true", "false"):
        raise ConfigError("ENABLE_SCHEDULED_WORKOUTS must be true or false")

    poll = get("HEVY_POLL_INTERVAL_SECONDS") or "60"
    if not poll.isascii() or not poll.isdigit() or int(poll) < _MIN_POLL_SECONDS:
        raise ConfigError(f"HEVY_POLL_INTERVAL_SECONDS must be a whole number of seconds, {_MIN_POLL_SECONDS} or more")

    zone = None
    if get("TZ"):
        try:
            zone = ZoneInfo(get("TZ"))
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ConfigError(f"TZ is not a time zone name such as America/Los_Angeles: {get('TZ')!r}") from e

    level = get("LOG_LEVEL").upper() or "INFO"
    if level not in _LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {', '.join(_LEVELS)}")

    log_format = get("LOG_FORMAT").lower() or "text"
    if log_format not in ("text", "json"):
        raise ConfigError("LOG_FORMAT must be text or json")

    return Config(
        hevy_api_key=api_key,
        garmin_token=get("GARMIN_TOKEN") or None,
        include_folders=tuple(part.strip() for part in get("INCLUDE_HEVY_FOLDERS").split(",") if part.strip()),
        custom_exercises=_custom_exercises(get("CUSTOM_EXERCISE_MAP")),
        scheduled=scheduled == "true",
        hevy_session=get("HEVY_SESSION") or None,
        poll_seconds=int(poll),
        zone=zone,
        # The image sets DATA_DIR=/data; a run from a clone keeps its tokens beside the code.
        data_dir=Path(get("DATA_DIR") or "data"),
        log_level=level,
        log_format=log_format,
    )


def _custom_exercises(value: str) -> dict[str, GarminExercise]:
    """CUSTOM_EXERCISE_MAP as each Hevy title or template id with its Garmin exercise (C-11).

    Split on the last `=`, so a title holding one still works; a title holding a
    comma can't be written, and goes by its id instead. A pair Garmin doesn't
    have exits here, so a typo is seen at startup rather than as a refused
    workout (TJ, 2026-11-10, #24).
    """
    garmin = garmin_exercises()
    found: dict[str, GarminExercise] = {}
    for entry in (part.strip() for part in value.split(",")):
        if not entry:
            continue
        key, equals, pair = entry.rpartition("=")
        category, slash, name = pair.strip().partition("/")
        key, category, name = key.strip(), category.strip(), name.strip()
        if not (equals and key and slash and category and name) or "/" in name:
            raise ConfigError(
                f"CUSTOM_EXERCISE_MAP entry {entry!r} is not title-or-id=CATEGORY/NAME, "
                "as in My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE"
            )
        if name not in garmin.get(category, ()):
            raise ConfigError(
                f"CUSTOM_EXERCISE_MAP names {category}/{name}, which Garmin doesn't have. "
                f"Use a category and an exercise from {_GARMIN_LIST}"
            )
        if key in found:
            raise ConfigError(f"CUSTOM_EXERCISE_MAP names {key!r} twice; keep one entry for it")
        found[key] = GarminExercise(category, name)
    return found
