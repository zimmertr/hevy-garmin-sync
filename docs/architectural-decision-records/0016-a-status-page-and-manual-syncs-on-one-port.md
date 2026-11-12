# 0016. The app serves a status page and its API on one port, takes manual syncs through it, and a rejected sign-in degrades its service instead of exiting

- Status: Accepted. Supersedes 0007
- Date: 2026-11-12
- Decider: TJ, on #31: a manual sync and a forced one (2026-11-10), an API on a port with a web page (2026-11-11), no sign-in, the variable's name, the page's look and contents, the probes, and a rejected sign-in that no longer exits (2026-11-11 and 2026-11-12).
- Issues and PRs: #31, #59, #57 (settings from the page, not built)
- Cited in code as: W-1 to W-9, C-13
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec section 12a, C-13, S-3, F-2, F-4, F-4a, F-4b, O-1, O-2 and D-4 in [`docs/SPEC.md`](../SPEC.md)

## Context

The app synced when Hevy changed, at midnight and at startup, and a restart was the only manual way in. A restart doesn't send an unchanged workout to the watch again or rewrite one, and some Hevy Trainer inputs were read only at startup, midnight and after a logged workout. On 2026-11-11 TJ changed one exercise's unit in Hevy and nothing reached Garmin until a restart. The log was the only way to learn whether Garmin refused a workout, which Garmin exercise a Hevy exercise got, or what weight Hevy Trainer worked out. A rejected credential exited the app (0007), and each restart tried the dead token again; a rejected `HEVY_SESSION` stopped routines too, which don't need it.

## Decision

One port, `HTTP_PORT` (default 8080), on every interface, served by `http.server.ThreadingHTTPServer` on a second thread of the one process (`server.py`). It serves the page and its files, `/api/status`, `/api/logs`, `POST /api/sync`, `/healthz` and `/readyz`. Routing is a plain function, `route`, so tests need no socket. The server thread reads the status the loop swaps in whole after each step (`status.py`) and asks for a sync through `Requests.ask` in `app.py`; it never calls Hevy or Garmin, so one process still holds the rotating tokens (A-7).

Every manual sync, from the page, the API or `sync`, goes through `Requests`: one limit of 60 seconds after the last one ends, a request while one waits or runs joins it, and the wake-up ends the loop's wait for the next poll. A wait after a Garmin failure or rate limit is never cut short. A plain sync is a full reconcile that also sends every workout to the watch again and reads Hevy Trainer's inputs again. A forced one also rewrites every workout in place, ignoring its `Version`, and reads each exercise's last sets again.

The page is plain HTML, CSS and JavaScript under `src/hevy_garmin_sync/web/`, with the Barlow fonts and the icon, and no build step. They are separate files, not inline, because every reply carries `Content-Security-Policy: default-src 'self'` with no `'unsafe-inline'`: a Hevy title that slipped past escaping still couldn't run. The log is kept in memory, the last 5,000 lines (`logbuffer.py`).

A rejected sign-in records the fix in `App._rejected`, stops calling that service and keeps running. `/readyz` is 503 while any is rejected. `/healthz` is 200 while the loop is inside a deadline it sets before each wait (the wait plus 2 minutes) and each pass (15 minutes), so a long backoff counts as alive and the liveness probe never restarts the pod into another Garmin sign-in. The chart's Service sets `publishNotReadyAddresses`, so the page that shows the fix stays reachable while the pod is unready.

## Evidence

- 2026-11-11: TJ set one exercise's unit to kilograms in Hevy. Nothing changed in Garmin for seven minutes; after a restart the app used kilograms for it (spec U-15).
- 2026-11-12: a new pod's first Garmin call failed on a DNS lookup and recovered by itself a minute later. A liveness probe that failed there would have restarted it.
- 2026-11-12: TJ opened `https://hevy.com/routine/<id>` with a routine's public API id, and it showed the routine (`docs/DATA.md`).
- GitHub serves a repo its own `.github/ISSUE_TEMPLATE/` or the shared defaults from `zimmertr/.github`, never both, so the repo keeps copies of the shared templates beside `exercise-match.yml` (zimmertr/yggdrasil record 0058).

## Alternatives rejected

- **A `sync` command that signals the app with `SIGUSR1`**: no port, but it can only start a sync and can't show anything.
- **A request file in `DATA_DIR`**: starts up to one poll later, and a stale file needs cleaning up.
- **A second process that syncs once and exits**: two processes refresh the same rotating Garmin token and lock each other out (A-7).
- **A sign-in on the page**: TJ, 2026-11-11, "That's fine, it's just me." `compose.yaml` publishes the port on `127.0.0.1` only.
- **Inline script and styles in one HTML file**: the Content-Security-Policy would need `'unsafe-inline'`.
- **A Compose healthcheck**: Compose marks a container unhealthy but doesn't restart it.
- **Keep exiting on a rejected credential** (0007): each restart tried the dead token again, and a rejected `HEVY_SESSION` stopped routines.

## Consequences

`tests/test_server.py`, `tests/test_status.py`, `tests/test_logbuffer.py`, `tests/test_cli.py` (`SyncTest`), `tests/test_app.py` (`ManualSyncTest`, `RequestsTest` and the rejection tests in `StartupTest` and `FailureTest`) and the chart renders in `.github/workflows/pr.yml` hold it. Anyone who can reach the port sees workout names and weights and can start a sync or a forced one; from a clone the port is open to the local network. A forced sync undoes hand edits in Garmin Connect and costs a Garmin write per workout and a Hevy read per exercise. A plain sync costs about 3 Garmin calls per workout. A fixed credential still needs a restart, which a changed Secret or `.env` does anyway. The issue templates copied from yggdrasil don't follow later changes to the shared ones.
