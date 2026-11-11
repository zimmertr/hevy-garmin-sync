"""Compares Garmin's exercise list and Hevy's published API spec with the copies in tests/data.

The tests check every exercise map row against `tests/data/garmin_exercises.json` (spec F-51) and
read Hevy's enum values from `tests/data/hevy_api.json`, so a change upstream that nobody copied
still passes CI. This is what notices: `.github/workflows/upstream-check.yml` runs it weekly, and
`make upstream-check` and `make upstream-update` run it in Docker (#26, record 0010).

Exit codes: 0 when both copies match, 1 on a difference (printed, and written to --report), 2 when
a source could not be fetched or read. With --write, a difference rewrites the copies and exits 0.

Standard library only, so the workflow runs it without installing anything.
"""

import argparse
import http.client
import json
import re
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
GARMIN_URL = "https://connect.garmin.com/web-data/exercises/Exercises.json"
HEVY_URL = "https://api.hevyapp.com/docs/swagger-ui-init.js"
# Both sources are public. A request names no app, account or person, and carries no token or cookie.
USER_AGENT = "Mozilla/5.0 (compatible; upstream-check)"
TIMEOUT_SECONDS = 30
SAME, DIFFERENT, UNCHECKED = 0, 1, 2
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "patch", "head", "options", "trace"})
# The enums the tests read, by where Hevy's spec defines them. Only these are kept: the whole spec's
# descriptions and examples change often, and a copy of them would open an issue for nothing.
HEVY_ENUMS: dict[str, tuple[str, ...]] = {
    "exercise_template_type": ("components", "schemas", "CustomExerciseType"),
    "equipment": ("components", "schemas", "EquipmentCategory"),
    "muscle_group": ("components", "schemas", "MuscleGroup"),
    "set_type": ("components", "schemas", "PostRoutinesRequestSet", "properties", "type"),
}
# GitHub refuses an issue body over 65,536 characters; a change this big is read in the PR's diff.
LISTED = 100


class SourceError(Exception):
    """A source could not be fetched, or no longer has the shape this script reads."""


class Response(Protocol):
    def read(self) -> bytes: ...


class Opener(Protocol):
    def __call__(self, url: urllib.request.Request, *, timeout: float) -> AbstractContextManager[Response]: ...


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    copy: str
    reduce: Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class Difference:
    added: list[str]
    removed: list[str]

    def __bool__(self) -> bool:
        return bool(self.added or self.removed)


def fetch(url: str, opener: Opener) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except (OSError, http.client.HTTPException, UnicodeDecodeError) as error:
        raise SourceError(f"{url} could not be fetched: {error}") from error


def reduce_garmin(text: str) -> dict[str, Any]:
    """Garmin's list as its category keys, each with its sorted exercise keys."""
    try:
        categories = json.loads(text)["categories"]
        reduced = {category: sorted(body["exercises"]) for category, body in categories.items()}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise SourceError(f"Garmin's exercise list is no longer categories, each with exercises: {error!r}") from error
    if not reduced:
        raise SourceError("Garmin's exercise list has no categories")
    return dict(sorted(reduced.items()))


def spec_from_script(text: str) -> dict[str, Any]:
    """The OpenAPI document that swagger-ui-express writes into the docs page's script as `"swaggerDoc": {...}`."""
    found = re.search(r'"swaggerDoc"\s*:\s*(?=\{)', text)
    if found is None:
        raise SourceError("Hevy's docs script no longer holds a swaggerDoc object")
    try:
        decoded: tuple[dict[str, Any], int] = json.JSONDecoder().raw_decode(text, found.end())
    except json.JSONDecodeError as error:
        raise SourceError(f"Hevy's swaggerDoc is not JSON: {error}") from error
    return decoded[0]


def enum_paths(node: Any, path: tuple[str, ...] = ()) -> Iterator[str]:
    """Where a spec defines its enums, for the error that says one of ours moved."""
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            yield "/".join(path)
        for key, value in node.items():
            yield from enum_paths(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from enum_paths(value, (*path, str(index)))


def enum_values(spec: dict[str, Any], where: tuple[str, ...]) -> list[str]:
    node: Any = spec
    for key in where:
        node = node.get(key) if isinstance(node, dict) else None
    values = node.get("enum") if isinstance(node, dict) else None
    if not isinstance(values, list) or not values:
        found = ", ".join(enum_paths(spec)) or "nowhere"
        raise SourceError(f"Hevy's spec has no enum at {'/'.join(where)}. It has enums at: {found}")
    return sorted(str(value) for value in values)


def reduce_hevy(text: str) -> dict[str, Any]:
    """Hevy's spec as each path with its methods, and the values of the enums in HEVY_ENUMS."""
    spec = spec_from_script(text)
    try:
        paths = {path: sorted(m for m in item if m in HTTP_METHODS) for path, item in spec["paths"].items()}
    except (KeyError, TypeError, AttributeError) as error:
        raise SourceError(f"Hevy's spec has no paths: {error!r}") from error
    if not paths:
        raise SourceError("Hevy's spec lists no paths")
    enums = {name: enum_values(spec, where) for name, where in HEVY_ENUMS.items()}
    return {"enums": enums, "paths": dict(sorted(paths.items()))}


SOURCES = (
    Source("Garmin's exercise list", GARMIN_URL, "garmin_exercises.json", reduce_garmin),
    Source("Hevy's API spec", HEVY_URL, "hevy_api.json", reduce_hevy),
)


def leaves(copy: Mapping[str, Any], path: tuple[str, ...] = ()) -> set[str]:
    """Every value in a copy with the keys above it, so `BENCH_PRESS > BARBELL_BENCH_PRESS`; an empty
    list or mapping is its own key, so a category that loses its last exercise still shows."""
    found: set[str] = set()
    for key, value in copy.items():
        here = (*path, str(key))
        if isinstance(value, Mapping) and value:
            found |= leaves(value, here)
        elif isinstance(value, list) and value:
            found |= {" > ".join((*here, str(item))) for item in value}
        else:
            found.add(" > ".join(here))
    return found


def compare(committed: Mapping[str, Any], fetched: Mapping[str, Any]) -> Difference:
    old, new = leaves(committed), leaves(fetched)
    return Difference(added=sorted(new - old), removed=sorted(old - new))


def listed(label: str, items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [f"{label} ({len(items)}):", *(f"- `{item}`" for item in items[:LISTED])]
    if len(items) > LISTED:
        lines.append(f"- and {len(items) - LISTED} more")
    return [*lines, ""]


def section(source: Source, outcome: Difference | SourceError) -> str:
    lines = [f"## {source.title}", "", f"{source.url} against `tests/data/{source.copy}`.", ""]
    if isinstance(outcome, SourceError):
        lines += [f"Could not check: {outcome}", ""]
    elif outcome:
        lines += listed("Added", outcome.added) + listed("Removed", outcome.removed)
    else:
        lines += ["No difference.", ""]
    return "\n".join(lines)


def dump(copy: Mapping[str, Any]) -> str:
    """The copies' one format: one-space indent and sorted keys, as garmin_exercises.json was first written."""
    return json.dumps(copy, indent=1, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None, opener: Opener = urllib.request.urlopen, data: Path = DATA) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--write", action="store_true", help="rewrite the copies that differ, and exit 0")
    parser.add_argument("--report", type=Path, help="also write the report, in Markdown, to this file")
    args = parser.parse_args(argv)

    sections, changed, failed = [], {}, False
    for source in SOURCES:
        outcome: Difference | SourceError
        try:
            fetched = source.reduce(fetch(source.url, opener))
        except SourceError as error:
            outcome, failed = error, True
        else:
            path = data / source.copy
            committed = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            outcome = compare(committed, fetched)
            if outcome:
                changed[path] = fetched
        sections.append(section(source, outcome))

    text = "\n".join(sections)
    print(text, end="")
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    if failed:
        return UNCHECKED
    if args.write:
        # Only once both sources were read, so a half-updated pair never reaches a PR.
        for path, fetched in changed.items():
            path.write_text(dump(fetched), encoding="utf-8")
        return SAME
    return DIFFERENT if changed else SAME


if __name__ == "__main__":  # pragma: no cover (the tests call main(); this line only runs from a shell)
    raise SystemExit(main())
