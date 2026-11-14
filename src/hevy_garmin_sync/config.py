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
    previous_values: bool
    hevy_session: str | None
    poll_seconds: int
    zone: ZoneInfo | None
    data_dir: Path
    log_level: str
    log_format: str
    http_port: int = 8080  # C-13
    preview_pr: str | None = None  # C-14
    preview_commit: str | None = None  # C-15

    def summary(self) -> dict[str, str]:
        """The effective configuration for the startup log, secrets redacted (O-3c)."""
        if self.preview_pr:
            credentials = dict.fromkeys(("HEVY_API_KEY", "GARMIN_TOKEN", "HEVY_SESSION"), "ignored (a preview)")
            return credentials | self._settings() | {
                "PREVIEW_PR": self.preview_pr,
                "PREVIEW_COMMIT": self.preview_commit or "unset",
            }
        return {
            "HEVY_API_KEY": "set",
            "GARMIN_TOKEN": "set" if self.garmin_token else "unset (using the token in DATA_DIR)",
            "HEVY_SESSION": "set (Hevy Trainer on)" if self.hevy_session else "unset (Hevy Trainer off)",
        } | self._settings()

    def _settings(self) -> dict[str, str]:
        return {
            "INCLUDE_HEVY_FOLDERS": ", ".join(self.include_folders) or "unset (all routines)",
            # A count only: the entries hold a user's own exercise titles (C-11).
            "CUSTOM_EXERCISE_MAP": (
                f"set ({len(self.custom_exercises)} {'entry' if len(self.custom_exercises) == 1 else 'entries'})"
                if self.custom_exercises
                else "unset (custom exercises go by muscle group and equipment)"
            ),
            "ENABLE_SCHEDULED_WORKOUTS": str(self.scheduled).lower(),
            "ENABLE_PREVIOUS_VALUES": str(self.previous_values).lower(),
            "HEVY_POLL_INTERVAL_SECONDS": str(self.poll_seconds),
            "TZ": self.zone.key if self.zone else "unset (using the Garmin profile's time zone)",
            "DATA_DIR": str(self.data_dir),
            "LOG_LEVEL": self.log_level,
            "LOG_FORMAT": self.log_format,
            "HTTP_PORT": str(self.http_port),
        }


def load(env: Mapping[str, str]) -> Config:
    def get(name: str) -> str:
        return env.get(name, "").strip()

    # A preview runs on made-up accounts and ignores every credential, so one copied into it by mistake
    # can't sign the live app out (C-14, W-10).
    preview_pr = get("PREVIEW_PR") or None
    if preview_pr and not (preview_pr.isascii() and preview_pr.isdigit()):
        raise ConfigError("PREVIEW_PR must be a pull request's number, such as 63")
    preview_commit = get("PREVIEW_COMMIT").lower() or None
    if preview_commit and not (preview_commit.isascii() and all(c in "0123456789abcdef" for c in preview_commit)):
        raise ConfigError("PREVIEW_COMMIT must be a commit's hash, such as 7bc73bc")

    api_key = get("HEVY_API_KEY")
    if not api_key and not preview_pr:
        raise ConfigError("HEVY_API_KEY is required: create a key at https://hevy.com/settings?developer (Hevy Pro)")

    scheduled = get("ENABLE_SCHEDULED_WORKOUTS").lower() or "true"
    if scheduled not in ("true", "false"):
        raise ConfigError("ENABLE_SCHEDULED_WORKOUTS must be true or false")

    previous_values = get("ENABLE_PREVIOUS_VALUES").lower() or "true"
    if previous_values not in ("true", "false"):
        raise ConfigError("ENABLE_PREVIOUS_VALUES must be true or false")

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

    port = get("HTTP_PORT") or "8080"
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ConfigError("HTTP_PORT must be a whole number from 1 to 65535")

    return Config(
        hevy_api_key="" if preview_pr else api_key,
        garmin_token=None if preview_pr else get("GARMIN_TOKEN") or None,
        include_folders=tuple(part.strip() for part in get("INCLUDE_HEVY_FOLDERS").split(",") if part.strip()),
        custom_exercises=_custom_exercises(get("CUSTOM_EXERCISE_MAP")),
        scheduled=scheduled == "true",
        previous_values=previous_values == "true",
        hevy_session=None if preview_pr else get("HEVY_SESSION") or None,
        poll_seconds=int(poll),
        zone=zone,
        # The image sets DATA_DIR=/data; a run from a clone keeps its tokens beside the code.
        data_dir=Path(get("DATA_DIR") or "data"),
        log_level=level,
        log_format=log_format,
        http_port=int(port),
        preview_pr=preview_pr,
        preview_commit=preview_commit,
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
