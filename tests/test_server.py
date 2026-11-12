"""The status page and its API: every route, the refusals, and the headers every reply carries (spec W-1)."""

import json
import logging
import unittest
from unittest import mock

from hevy_garmin_sync import server
from hevy_garmin_sync.logbuffer import LogBuffer
from tests import fixtures

HOST = {"host": "nas.local:8080"}


class RouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = fixtures.FakeLoop()
        self.logs = LogBuffer()

    def route(self, method: str, target: str, headers: dict[str, str] | None = None) -> server.Reply:
        return server.route(method, target, HOST | (headers or {}), self.loop, self.logs)

    def test_the_page_and_its_files_are_served_from_the_package(self) -> None:
        page = self.route("GET", "/")
        self.assertEqual((page.code, page.content_type), (200, "text/html; charset=utf-8"))
        self.assertIn(b'<script src="/app.js" defer></script>', page.body)
        for path, kind in (
            ("/app.js", "text/javascript"),
            ("/app.css", "text/css"),
            ("/icon.svg", "image/svg+xml"),
            ("/barlow-400.woff2", "font/woff2"),
            ("/barlow-semi-condensed-700.woff2", "font/woff2"),
        ):
            with self.subTest(path=path):
                reply = self.route("GET", path)
                self.assertEqual(reply.code, 200)
                self.assertTrue(reply.content_type.startswith(kind))
                self.assertTrue(reply.body)

    def test_every_file_the_page_names_is_served(self) -> None:
        # The page loads nothing from anywhere else: it works with no internet.
        page = self.route("GET", "/").body.decode() + self.route("GET", "/app.css").body.decode()
        for name in ("/app.css", "/app.js", "/icon.svg", "/barlow-400.woff2", "/barlow-400-italic.woff2"):
            with self.subTest(name=name):
                self.assertIn(name, page)
                self.assertEqual(self.route("GET", name).code, 200)

    def test_the_status_is_the_one_the_loop_published(self) -> None:
        reply = self.route("GET", "/api/status")
        self.assertEqual((reply.code, reply.content_type), (200, "application/json"))
        self.assertEqual(json.loads(reply.body), self.loop.status)

    def test_the_log_is_served_newest_first_page_and_older_by_line_number(self) -> None:
        logger = logging.getLogger("test_server")
        logger.addHandler(self.logs)
        self.addCleanup(logger.removeHandler, self.logs)
        logger.propagate = False
        self.addCleanup(setattr, logger, "propagate", True)
        logger.setLevel(logging.INFO)
        for i in range(5):
            logger.info("line %d", i)
        newest = json.loads(self.route("GET", "/api/logs?size=2").body)
        self.assertEqual([line["message"] for line in newest["lines"]], ["line 3", "line 4"])
        self.assertTrue(newest["more"])
        older = json.loads(self.route("GET", f"/api/logs?size=200&before={newest['lines'][0]['seq']}").body)
        self.assertEqual([line["message"] for line in older["lines"]], ["line 0", "line 1", "line 2"])
        self.assertFalse(older["more"])

    def test_a_bad_log_query_is_refused(self) -> None:
        for target in ("/api/logs?before=x", "/api/logs?size=0", "/api/logs?size=201", "/api/logs?size=-1"):
            with self.subTest(target=target):
                self.assertEqual(self.route("GET", target).code, 400)

    def test_a_sync_asked_for_starts_and_force_is_passed_on(self) -> None:
        plain = self.route("POST", "/api/sync")
        forced = self.route("POST", "/api/sync?force=true")
        self.assertEqual((plain.code, json.loads(plain.body)), (202, {"result": "started", "force": False}))
        self.assertEqual(json.loads(forced.body)["force"], True)
        self.assertEqual(self.loop.requests.asked, [False, True])

    def test_a_sync_within_a_minute_is_refused_with_the_seconds_left(self) -> None:
        self.loop.requests.answer = ("wait", 46)
        reply = self.route("POST", "/api/sync")
        self.assertEqual((reply.code, json.loads(reply.body)), (429, {"result": "wait", "seconds": 46}))
        self.assertEqual(reply.headers, {"Retry-After": "46"})

    def test_a_sync_that_joins_one_says_so(self) -> None:
        self.loop.requests.answer = ("joined", 0)
        self.assertEqual(json.loads(self.route("POST", "/api/sync").body)["result"], "joined")

    def test_a_post_from_another_sites_page_is_refused_and_asks_for_nothing(self) -> None:
        reply = self.route("POST", "/api/sync?force=true", {"origin": "https://evil.example"})
        self.assertEqual(reply.code, 403)
        self.assertEqual(self.loop.requests.asked, [])

    def test_a_post_from_the_page_itself_or_with_no_origin_is_allowed(self) -> None:
        for origin in ({"origin": "http://NAS.local:8080"}, {}):
            with self.subTest(origin=origin):
                self.assertEqual(self.route("POST", "/api/sync", origin).code, 202)

    def test_health_follows_the_loop_and_readiness_the_sign_ins(self) -> None:
        self.assertEqual(self.route("GET", "/healthz").code, 200)
        self.assertEqual(self.route("GET", "/readyz").code, 200)
        self.loop.is_alive = self.loop.is_ready = False
        self.assertEqual(self.route("GET", "/healthz").code, 503)
        self.assertEqual(self.route("GET", "/readyz").code, 503)

    def test_the_wrong_method_and_an_unknown_path_are_refused(self) -> None:
        self.assertEqual(self.route("POST", "/").code, 405)
        self.assertEqual(self.route("GET", "/api/sync").code, 405)
        self.assertEqual(self.route("GET", "/../src/hevy_garmin_sync/config.py").code, 404)
        self.assertEqual(self.route("GET", "/data/garmin_tokens.json").code, 404)


class HandlerTest(unittest.TestCase):
    """The http.server wrapper, over an in-memory connection."""

    def serve(self, raw: bytes) -> bytes:
        connection = fixtures.FakeSocket(raw)
        handle = server.handler(fixtures.FakeLoop(), LogBuffer())
        handle(connection, ("127.0.0.1", 1234), mock.Mock())  # type: ignore[arg-type]
        return connection.reply

    def test_a_reply_carries_its_type_its_length_and_the_security_headers(self) -> None:
        reply = self.serve(b"GET /api/status HTTP/1.1\r\nHost: nas.local:8080\r\n\r\n")
        head, _, body = reply.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.0 200"))
        self.assertIn(b"Content-Type: application/json", head)
        self.assertIn(f"Content-Length: {len(body)}".encode(), head)
        self.assertIn(b"Content-Security-Policy: default-src 'self'", head)
        self.assertIn(b"X-Content-Type-Options: nosniff", head)
        self.assertIn(b"Server: hevy-garmin-sync\r\n", head)

    def test_a_post_reaches_the_route_and_its_extra_headers_are_sent(self) -> None:
        loop = fixtures.FakeLoop()
        loop.requests.answer = ("wait", 5)
        connection = fixtures.FakeSocket(b"POST /api/sync HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n")
        handle = server.handler(loop, LogBuffer())
        handle(connection, ("127.0.0.1", 1234), mock.Mock())  # type: ignore[arg-type]
        self.assertIn(b"Retry-After: 5", connection.reply)
        self.assertEqual(loop.requests.asked, [False])

    def test_requests_are_logged_at_debug_only(self) -> None:
        with self.assertLogs("hevy_garmin_sync.server", "DEBUG") as logs:
            self.serve(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertTrue(all(line.startswith("DEBUG") for line in logs.output))


class StartTest(unittest.TestCase):
    def test_it_listens_on_every_interface_on_a_daemon_thread(self) -> None:
        with (
            mock.patch.object(server, "ThreadingHTTPServer") as httpd,
            mock.patch("threading.Thread") as thread,
            self.assertLogs("hevy_garmin_sync.server", "INFO") as logs,
        ):
            started = server.start(9090, fixtures.FakeLoop(), LogBuffer())
        self.assertIs(started, httpd.return_value)
        self.assertEqual(httpd.call_args.args[0], ("0.0.0.0", 9090))
        self.assertTrue(started.daemon_threads)
        self.assertEqual(thread.call_args.kwargs, {"target": started.serve_forever, "name": "http", "daemon": True})
        thread.return_value.start.assert_called_once_with()
        self.assertIn("Status page on port 9090", logs.output[0])


if __name__ == "__main__":
    unittest.main()
