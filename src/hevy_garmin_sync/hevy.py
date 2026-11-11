"""Hevy's public API (api.hevyapp.com/docs), read with the Pro API key (spec A-1).

Read only: the app never writes to Hevy (S-1). Hevy's only webhook reports a
saved workout, and nothing reports a changed routine, so the app polls. A
webhook would also need a listening port, which F-2 rules out.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import requests

from . import __version__
from .errors import NotFound, RateLimited, Refused, Rejected, ServiceError, Unavailable

BASE = "https://api.hevyapp.com/v1"
TIMEOUT_SECONDS = 30  # O-1a
USER_AGENT = f"hevy-garmin-sync/{__version__} (+https://github.com/zimmertr/hevy-garmin-sync)"
KEY_FIX = "check HEVY_API_KEY against https://hevy.com/settings?developer (the key needs Hevy Pro)"
_PAGE = 10  # the API's maximum for routines, folders, workouts and events
_TEMPLATE_PAGE = 100
# An exercise template's `type`, in both spellings. The short ones are what the API returned on
# 2026-11-10; the long ones are what its reference lists.
WEIGHTED_BODYWEIGHT = ("bodyweight_weighted", "bodyweight_reps")
ASSISTED = ("bodyweight_assisted", "bodyweight_assisted_reps")

Json = dict[str, Any]


def get_json(send: Callable[[], requests.Response]) -> Any:
    """Run one request and return its JSON, or raise one of the app's own errors.

    Shared with the private client (hevy_private.py): both services answer
    the same way.
    """
    try:
        reply = send()
    except requests.RequestException as e:
        # Never the exception's text: it can carry the whole URL.
        raise Unavailable(type(e).__name__) from e
    if reply.status_code >= 400:
        raise by_status(reply.status_code, f"HTTP {reply.status_code}: {reply.text[:200]}")
    try:
        return reply.json()
    except ValueError as e:
        raise Unavailable(f"HTTP {reply.status_code} with a body that is not JSON") from e


def by_status(status: int, message: str) -> ServiceError:
    if status in (401, 403):
        return Rejected(message)
    if status == 429:
        return RateLimited(message)
    if status == 404:
        return NotFound(message)
    if status < 500:
        return Refused(message)
    return Unavailable(message)


class Hevy:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._headers = {"api-key": api_key, "Accept": "application/json", "User-Agent": USER_AGENT}
        self._templates: dict[str, Json | None] | None = None
        self.calls = 0  # logged per poll at DEBUG (U-9)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls += 1
        return get_json(
            lambda: self._session.get(f"{BASE}{path}", headers=self._headers, params=params, timeout=TIMEOUT_SECONDS)
        )

    def _pages(self, path: str, key: str, size: int = _PAGE, params: dict[str, Any] | None = None) -> Iterator[Json]:
        """Every item of a paged list. A page that fails raises, so a caller never sees part of a list (F-14a)."""
        page = 1
        while True:
            body = self._get(path, {**(params or {}), "page": page, "pageSize": size})
            yield from body.get(key) or []
            if page >= int(body.get("page_count") or 1):
                return
            page += 1

    def folders(self) -> list[Json]:
        return list(self._pages("/routine_folders", "routine_folders"))

    def routines(self) -> list[Json]:
        return list(self._pages("/routines", "routines"))

    def template(self, template_id: str) -> Json | None:
        """One exercise template: built-in or the user's own. None when Hevy has none by that id.

        The whole list is read once, on first use, and kept (F-3b); a template
        created later is read by itself.
        """
        if self._templates is None:
            listed = self._pages("/exercise_templates", "exercise_templates", _TEMPLATE_PAGE)
            self._templates = {str(t.get("id")): t for t in listed}
        if template_id not in self._templates:
            try:
                body = self._get(f"/exercise_templates/{template_id}")
                self._templates[template_id] = body.get("exercise_template", body)
            except Refused:
                self._templates[template_id] = None
        return self._templates[template_id]

    def workout_events(self, since: datetime) -> list[Json]:
        """Workouts saved, edited or deleted since `since`, newest first."""
        return list(self._pages("/workouts/events", "events", params={"since": _utc(since)}))

    def exercise_history(self, template_id: str, start: datetime, end: datetime) -> list[Json]:
        """Every logged set of one exercise between two instants (F-46)."""
        body = self._get(f"/exercise_history/{template_id}", {"start_date": _utc(start), "end_date": _utc(end)})
        found: list[Json] = body.get("exercise_history") or []
        return found


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
