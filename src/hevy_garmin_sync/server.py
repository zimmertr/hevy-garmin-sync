"""The status page and its API on `HTTP_PORT` (spec W-1).

`route` is a plain function from a request to a reply, so tests need no
socket. `start` wraps it in the standard library's threading HTTP server on a
second thread. That thread reads the status the loop published and asks for a
manual sync; it never calls Hevy or Garmin.

There is no sign-in: anyone who can reach the port sees the page and can
press its buttons (TJ, 2026-11-11). A POST from another site's page is refused,
so a link elsewhere can't start a sync from the user's browser.
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from .logbuffer import PAGE, LogBuffer

log = logging.getLogger(__name__)

# The page's own files, read once. No CDN: the page works with no internet.
_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/barlow-400.woff2": ("barlow-400.woff2", "font/woff2"),
    "/barlow-400-italic.woff2": ("barlow-400-italic.woff2", "font/woff2"),
    "/barlow-500.woff2": ("barlow-500.woff2", "font/woff2"),
    "/barlow-600.woff2": ("barlow-600.woff2", "font/woff2"),
    "/barlow-semi-condensed-700.woff2": ("barlow-semi-condensed-700.woff2", "font/woff2"),
}
# Everything the page loads comes from this port; nothing else may run or load.
_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class _Requests(Protocol):
    def ask(self, force: bool) -> tuple[str, int]: ...


class Loop(Protocol):
    """What the server reads from the app: the published status, health, and the door for a manual sync."""

    @property
    def status(self) -> dict[str, Any]: ...

    @property
    def requests(self) -> _Requests: ...

    def alive(self) -> bool: ...

    def ready(self) -> bool: ...


@dataclass(frozen=True)
class Reply:
    code: int
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


def _json(code: int, value: Any, headers: dict[str, str] | None = None) -> Reply:
    return Reply(code, json.dumps(value).encode(), "application/json", headers or {})


def _text(code: int, text: str) -> Reply:
    return Reply(code, f"{text}\n".encode())


def _file(name: str) -> bytes:
    return (resources.files("hevy_garmin_sync") / "web" / name).read_bytes()


def _same_origin(headers: dict[str, str]) -> bool:
    """A browser sends Origin on a POST. `sync` and curl send none, and are allowed (W-1)."""
    origin = headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc.lower() == headers.get("host", "").lower()


def route(method: str, target: str, headers: dict[str, str], loop: Loop, logs: LogBuffer) -> Reply:
    """One request to its reply. `headers` has lowercase names."""
    url = urlsplit(target)
    query = parse_qs(url.query)
    path = url.path
    if path in _FILES or path in ("/api/status", "/api/logs", "/healthz", "/readyz"):
        if method != "GET":
            return _text(405, "Use GET")
        if path in _FILES:
            name, kind = _FILES[path]
            return Reply(200, _file(name), kind)
        if path == "/api/status":
            return _json(200, loop.status)
        if path == "/api/logs":
            before, size = query.get("before", [""])[0], query.get("size", [str(PAGE)])[0]
            if (before and not before.isdigit()) or not size.isdigit() or not 1 <= int(size) <= PAGE:
                return _text(400, f"before must be a line number, and size a number from 1 to {PAGE}")
            return _json(200, logs.page(int(before) if before else None, int(size)))
        if path == "/healthz":
            # Alive during a wait after a failure too: a restart there signs in to Garmin again (W-7).
            return _text(200, "ok") if loop.alive() else _text(503, "the loop has stopped passing")
        return _text(200, "ready") if loop.ready() else _text(503, "a sign-in was rejected; see the status page")
    if path == "/api/sync":
        if method != "POST":
            return _text(405, "Use POST")
        if not _same_origin(headers):
            return _text(403, "A sync can only be asked for from this app's own page")
        force = query.get("force", ["false"])[0].lower() == "true"
        result, seconds = loop.requests.ask(force)
        if result == "wait":
            return _json(429, {"result": "wait", "seconds": seconds}, {"Retry-After": str(seconds)})
        return _json(202, {"result": result, "force": force})
    return _text(404, "Not found")


def handler(loop: Loop, logs: LogBuffer) -> type[BaseHTTPRequestHandler]:
    """http.server's request handler around `route`, with the headers every reply carries."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "hevy-garmin-sync"

        def version_string(self) -> str:
            return self.server_version  # the default adds Python's version after a space

        def _reply(self) -> None:
            headers = {name.lower(): value for name, value in self.headers.items()}
            reply = route(self.command, self.path, headers, loop, logs)
            self.send_response(reply.code)
            for name, value in (_HEADERS | reply.headers | {"Content-Type": reply.content_type}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        do_GET = do_POST = do_PUT = do_DELETE = _reply  # http.server calls do_<METHOD>

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("HTTP %s", format % args)

    return Handler


def start(port: int, loop: Loop, logs: LogBuffer, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Serve on every interface, on a daemon thread, until `shutdown` (W-1)."""
    httpd = ThreadingHTTPServer((host, port), handler(loop, logs))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    log.info("Status page on port %d", port)
    return httpd
