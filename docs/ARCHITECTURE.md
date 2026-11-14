# Architecture

Where each part of the app lives. The behaviour is specified in [SPEC.md](SPEC.md); this page says which file does what.

## The repo

| Path | Holds |
|---|---|
| `src/hevy_garmin_sync/` | The Python package ([the modules](#the-modules)) |
| `src/hevy_garmin_sync/web/` | The status page: `index.html`, `app.css`, `app.js`, the icon and the Barlow fonts. Served as they are, with no build step |
| `src/hevy_garmin_sync/data/` | The two exercise tables the app ships, and the keys of Garmin's exercise list ([the exercise map](#the-exercise-map)) |
| `tests/` | `unittest` suites, one fixtures module with every fake, and in `tests/data` the copy of Hevy's API spec and the recorded reply shapes the fakes are held to |
| `scripts/` | `check_upstream.py`, the weekly upstream check: compares the copies of Garmin's list and Hevy's spec with their source ([CICD.md](CICD.md#the-upstream-check)). `live_check.py`, the run by hand against TJ's own accounts that records the shapes of Hevy's and Garmin's replies, puts a check workout on the watch and probes Garmin's step cap ([DEVELOPMENT.md](DEVELOPMENT.md#the-live-check)). Neither is in the image |
| `charts/hevy-garmin-sync-helm/` | The Helm chart: one Deployment, its PersistentVolumeClaim, Secret and Service |
| `compose.yaml` | The same container for Docker Compose |
| `Dockerfile` | The image: `python:3.15-slim`, the hashed lock, the package, `/data`, user 1000 |
| `.github/ISSUE_TEMPLATE/` | Copies of yggdrasil's shared issue templates, plus `exercise-match.yml`, which the status page's "Report this match" opens (spec W-5) |
| `.github/workflows/` | Callers of zimmertr/yggdrasil's modules, plus the chart's release jobs and the upstream check ([CICD.md](CICD.md)) |
| `docs/` | This set. [SPEC.md](SPEC.md) is the plan |

## The process

```mermaid
flowchart LR
  hevy["Hevy<br/>public API (routines)<br/>private API (Trainer)"] -->|poll every 60 s| app["hevy-garmin-sync<br/>one process"]
  app -->|create, update, delete workouts<br/>calendar entries, send to device| garmin["Garmin Connect"]
  garmin -->|phone sync| watch["Watch"]
  app <-->|rotated tokens| data[("/data volume")]
  browser["Browser, or the sync command"] <-->|status page, API<br/>HTTP_PORT| app
```

One long-running process (spec F-1). One thread runs the loop below and makes every Hevy and Garmin call. A second serves the status page and its API on `HTTP_PORT` (W-1): it reads the status the loop last published and can ask for a sync, and calls neither service.

1. **Start.** Read the environment. Anything wrong exits with a message naming the variable. Load the Garmin token, and the Hevy session if `HEVY_SESSION` is set, from `DATA_DIR`, seeding each from its variable when the variable is new (A-4).
2. **Check.** One call to each service. A rejected key, token or session stops that service, with the fix on the page and in the log (W-8). An outage is waited out.
3. **Full run.** Read every routine (and the Trainer program), read Garmin's workout list and the calendar, then create, update and delete until Garmin matches. Put each workout on today.
4. **Poll.** Every `HEVY_POLL_INTERVAL_SECONDS`, read Hevy again. Garmin is called only for what changed (F-4a). When Hevy Trainer's next workout changes, its calendar entry moves to it in the same poll (F-31). The workout events are read once, first, for Trainer and for last time's sets alike, and not at all when neither is on (F-4).
5. **Midnight.** At local midnight, a full run again: yesterday's calendar entries go and today's are added.
6. **Manual sync.** Sync now, Force sync or `sync` ends the wait for the next poll, and the next pass is a full run that also sends every workout to the watch again; a forced one rewrites every workout too (W-3, W-4). A wait after a failure is not cut short.
7. **Stop.** SIGTERM or SIGINT lets the write in progress finish and starts no new one.

A failing service gets its own wait, one minute doubling to thirty (O-1). A rate limit whose `Retry-After` says how long is waited that long instead, even past thirty, and never less than one poll. A workout Garmin refused is not a failing service: `sync.py` tries that one workout again 5 minutes later, then at gaps that double until midnight, then once a day, and a poll with no retry due calls Garmin for none of it (F-16, F-4a). Hevy's public API, Hevy's private API and Garmin each have one, so routines keep syncing while only Trainer is down, and Hevy is still read while Garmin is down. A rejected key, token or session is not waited out: the app stops calling that service and keeps the rest running, and `/readyz` turns 503 until a restart with a fixed value (W-8). `/healthz` stays 200 through every wait, so a probe never restarts the pod into another Garmin sign-in (W-7).

## The modules

| Module | Does |
|---|---|
| `cli.py` | The command line: no command runs the app, `login` signs in to Garmin, `sync` asks the running app for a sync through its API |
| `app.py` | The loop: startup checks, polling, the workout events read once a poll, midnight, the waits after a failure, manual syncs (`Requests`, the one door every request goes through), rejected sign-ins, health, stopping |
| `server.py` | The status page and its API on a second thread. `route` maps a request to a reply, so tests need no socket |
| `status.py` | What the page shows, built from what the loop knows: no secrets, times in ISO form |
| `logbuffer.py` | The last 5,000 log lines in memory, for the page |
| `config.py` | Reads and checks the environment variables, including each `CUSTOM_EXERCISE_MAP` pair against Garmin's list |
| `logs.py` | Text or JSON log lines |
| `store.py` | The data folder: whole-file writes that survive a kill, and which variable a stored token came from |
| `hevy.py` | Hevy's public API: folders, routines, exercise templates, workout events, exercise history |
| `hevy_private.py` | Hevy's private API, for Trainer only: the session and its refresh, the program, the preferences, the logged workouts |
| `routines.py` | Which routines sync, what each is called, and each routine as a planned workout |
| `trainer.py` | Trainer's program as planned workouts, and what is read when |
| `previous.py` | Last time's working sets of each exercise, for the status page: the newest logged workout that holds it, from its public history once, then kept current by the workout events. In memory only |
| `trainer_rules.py` | Trainer's arithmetic: the week, the next weight, warm-ups, rep ranges ([HEVY_TRAINER_RULES.md](HEVY_TRAINER_RULES.md)). No I/O |
| `exercises.py` | The Garmin exercise for each Hevy exercise, and the log line that names it for a custom one |
| `workout.py` | A planned workout as Garmin's workout JSON, each set's note, its version hash, and the description that marks it as the app's. No I/O |
| `garmin.py` | Garmin Connect through python-garminconnect: workouts, the calendar, Send to Device, saving the rotated token |
| `sync.py` | Makes Garmin match the plan: what to create, update, delete, schedule and send, and a report of each workout for the page |
| `login.py` | The `login` command: one sign-in, and the value for `GARMIN_TOKEN` on stdout |

`routines.py` and `trainer.py` each return a `Plans`: the workouts one source wants in Garmin. `sync.py` takes both and knows nothing about Hevy.

## How a workout is recognised

The app keeps no database. Each Garmin workout it makes carries four lines in its description: a first line that marks it as the app's, when it was last updated, the Hevy routine id or Trainer template id, and a six-character version hash of its contents (F-12). At a full run the app reads Garmin's workout list and matches on those. A workout without them is never touched. A workout is rewritten only when its version hash changes.

## The exercise map

Two CSV files in `src/hevy_garmin_sync/data/`:

- `exercise_map.csv`: one row per built-in Hevy exercise, by Hevy's exercise template id, naming a Garmin category and exercise.
- `custom_exercise_map.csv`: for a user's own exercises, and for a built-in the first table has no row for, by Hevy's primary muscle group and equipment.

A user's own exercise can instead be set in `CUSTOM_EXERCISE_MAP`, which wins over `custom_exercise_map.csv` and never applies to a built-in (C-11, F-54). `exercises.py` logs which Garmin exercise each custom exercise got.

`src/hevy_garmin_sync/data/garmin_exercises.json` holds the keys of Garmin Connect's own exercise list. A test fails when a table row names a pair that is not in it, and `config.py` refuses a `CUSTOM_EXERCISE_MAP` pair that is not in it at startup, which is why it ships in the image (F-51). A fix to a table is a one-line PR (F-54).

## The image

Built by the release for `linux/amd64` and `linux/arm64`, tagged with the version only, at `ghcr.io/zimmertr/hevy-garmin-sync` (record [0006](architectural-decision-records/0006-ghcr-and-a-digest-pinned-chart.md)). It runs as uid and gid 1000, and the only folder it writes is `/data` (`DATA_DIR`, spec C-8). The entry point is `python3 -m hevy_garmin_sync`. It exposes 8080, the status page.

## The chart

`hevy-garmin-sync-helm`, published with every release to `oci://ghcr.io/zimmertr` under the same version as the image, whose digest it pins (record 0006). One replica with the `Recreate` strategy, so two copies never run at once and fight over the rotating Garmin token (spec D-4). The container's root filesystem is read-only, so the data volume is the one place it can write (O-4, record [0008](architectural-decision-records/0008-read-only-root-filesystem-by-default.md)). A Service for the status page, `ClusterIP` unless the values say otherwise, which keeps the page reachable while the pod is unready. A liveness probe on `/healthz` and a readiness probe on `/readyz` (W-7). Values are in [CONFIGURATION.md](CONFIGURATION.md#chart-values).

## Where it runs for TJ

Kubernetes-Manifests `misc/hevy-garmin-sync` holds the chart version each release bumps, the values (the hand-made Secret and the volume's storage class) and the namespace. The misc ApplicationSet deploys it, so the bump PR is the deploy (spec D-7, record [0005](architectural-decision-records/0005-releases-deploy-through-the-live-folder.md)). It replaced hevy2garmin and hevy-trainer-sync on 2026-11-10.
