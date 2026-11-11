"""Hevy's private API, the one the Hevy apps use: Hevy Trainer only (spec section 6, A-3).

Trainer's program is not in the public API. This client reads it, the two sets
of preferences the weights depend on, and the user's logged workouts, with the
session the user copied from hevy.com. Read only. Hevy does not document this
API and can change or close it without notice; docs/DATA.md records what it
returned and when.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import requests

from .errors import ConfigError, NotFound, Refused, Rejected
from .hevy import TIMEOUT_SECONDS, USER_AGENT, get_json
from .store import Store

log = logging.getLogger(__name__)

BASE = "https://api.hevyapp.com"
SESSION = "hevy_session.json"
SESSION_FIX = (
    "copy the auth2.0-token cookie from hevy.com again (in a private window, closed without logging out) "
    "and set HEVY_SESSION to it"
)
# A fixed key hevy.com's own web client sends; it names the client, not the user.
_WEB_API_KEY = "shelobs_hevy_web"
_EPOCH = "1970-01-01T00:00:00.000Z"
# The page size the Hevy app asks for; 10 was answered with a 400 (2026-11-07).
_WORKOUT_PAGE = 3
_MAX_WORKOUT_PAGES = 200

Json = dict[str, Any]


def parse_time(raw: Any) -> datetime | None:
    """A Hevy time: Unix seconds, as a workout's start is kept, or ISO 8601."""
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return datetime.fromtimestamp(raw, UTC)
    if isinstance(raw, str):
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return None


def parse_cookie(value: str) -> Json:
    """The `auth2.0-token` cookie: URL-encoded JSON holding the access and refresh tokens."""
    try:
        tokens = json.loads(unquote(value.strip()))
    except ValueError as e:
        raise ConfigError(f"HEVY_SESSION is not the auth2.0-token cookie; {SESSION_FIX}") from e
    if not isinstance(tokens, dict) or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise ConfigError(f"HEVY_SESSION is not the whole auth2.0-token cookie; {SESSION_FIX}")
    return {key: tokens.get(key) for key in ("access_token", "refresh_token", "expires_at")}


class HevyPrivate:
    def __init__(
        self,
        tokens: Json,
        store: Store,
        session: requests.Session | None = None,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._tokens = tokens
        self._store = store
        self._session = session or requests.Session()
        self._utcnow = utcnow
        self.calls = 0

    @classmethod
    def open(cls, env_value: str, store: Store, session: requests.Session | None = None) -> HevyPrivate:
        """Load the session: the stored copy, unless HEVY_SESSION is new (A-4). No network."""
        stored = store.read(SESSION)
        if stored is None or not store.seeded_by(SESSION, env_value):
            tokens = parse_cookie(env_value)
            store.write(SESSION, json.dumps(tokens))
            store.mark_seed(SESSION, env_value)
        else:
            tokens = json.loads(stored)
        return cls(tokens, store, session)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": _WEB_API_KEY,
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-client-time": str(time.time()),
        }

    def _expired(self) -> bool:
        expires = parse_time(self._tokens.get("expires_at"))
        return expires is None or expires <= self._utcnow()

    def _refresh(self) -> None:
        """Trade the refresh token for a new pair, and save it before anything else.

        Hevy kills the old refresh token as it hands out the new one, so an
        unsaved pair is a lost session (O-3a). The old access token goes along
        in the header even when it has expired: without it Hevy answers 400.
        """
        self.calls += 1
        try:
            body = get_json(
                lambda: self._session.post(
                    f"{BASE}/auth/refresh_token",
                    headers=self._headers(),
                    json={"refresh_token": self._tokens["refresh_token"]},
                    timeout=TIMEOUT_SECONDS,
                )
            )
        except Refused as e:
            raise Rejected(f"Hevy would not refresh the session ({e})") from e
        if not isinstance(body, dict) or not body.get("access_token"):
            raise Rejected("Hevy's refresh reply held no access token")
        self._tokens = {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token") or self._tokens["refresh_token"],
            "expires_at": body.get("expires_at"),
        }
        self._store.write(SESSION, json.dumps(self._tokens))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET with the session, refreshed first when it has expired, and once more on a 401."""
        if self._expired():
            self._refresh()

        def send() -> Any:
            self.calls += 1
            return get_json(
                lambda: self._session.get(
                    f"{BASE}/{path}", headers=self._headers(), params=params, timeout=TIMEOUT_SECONDS
                )
            )

        try:
            return send()
        except Rejected:
            self._refresh()
            return send()

    def user_preferences(self) -> Json:
        """`username`, `weight_unit` and `first_weekday`."""
        body = self._get("v2/user_preferences")
        return body if isinstance(body, dict) else {}

    def trainer_preferences(self) -> Json:
        """`availableWeights`: the dumbbells, bars and plates Trainer rounds to."""
        body = self._get("hevy_trainer/user_preferences")
        return body if isinstance(body, dict) else {}

    def unit_overrides(self) -> Any:
        """The exercises the user logs in the other unit. Shape not yet seen (spec U-15)."""
        return self._get("exercise_template_units")

    def program(self) -> Json | None:
        """The Trainer program, or None when the account has none."""
        params = {"client_program_updated_at": _EPOCH, "client_next_workout_updated_at": _EPOCH}
        try:
            body = self._get("hevy_trainer/v3/program", params)
        except NotFound:
            return None
        program = body.get("program") if isinstance(body, dict) else None
        return program if isinstance(program, dict) else None

    def workouts_since(self, username: str, since: datetime) -> list[Json]:
        """The user's logged workouts from `since` on, each with its `trainer_workout_template_id`.

        The public API's workouts don't say which Trainer template they came from.
        """
        found: list[Json] = []
        for page in range(_MAX_WORKOUT_PAGES):
            params = {"username": username, "limit": _WORKOUT_PAGE, "offset": page * _WORKOUT_PAGE}
            body = self._get("user_workouts_paged", params)
            batch = body.get("workouts") if isinstance(body, dict) else None
            if not isinstance(batch, list) or not batch:
                break
            found.extend(w for w in batch if (parse_time(w.get("start_time")) or since) >= since)
            oldest = parse_time(batch[-1].get("start_time"))
            if len(batch) < _WORKOUT_PAGE or (oldest is not None and oldest < since):
                break
        return found
