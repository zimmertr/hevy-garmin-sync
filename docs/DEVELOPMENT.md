# Development

CI is the test runner. Branch from the latest `main`, open a draft PR early, push small commits, and read the jobs ([CICD.md](CICD.md)). Run something locally only when CI can't answer the question, and then in Docker: every target below runs in a container, and nothing installs on the workstation.

## Make targets

| Target | Runs |
|---|---|
| `make test` | The suite under coverage, as the `test` job does |
| `make test-one MODULE=tests.test_cli` | One module, verbose |
| `make lint` | ruff |
| `make typecheck` | mypy, strict |
| `make lint-docker` | hadolint on the Dockerfile |
| `make chart` | `helm lint`, a render, and the helm-unittest suites, as the `Chart / Chart` check does |
| `make build` | The image, tagged `hevy-garmin-sync:dev` |
| `make scan` | The release scan's rules against that build |
| `make lock` | Not a check: recompiles `requirements.txt` and `requirements-dev.txt` from the `.in` files, hashed. A pin change ships with its lock in the same PR |
| `make upstream-check` | Not a check: the weekly upstream check ([CICD.md](CICD.md#the-upstream-check)). Reads Garmin's exercise list and Hevy's published API spec and prints what differs from the repo's copies of them. Exits 3 on a difference and 2 when a source can't be read |
| `make upstream-update` | Not a check: the same, then rewrites the copies that differ |
| `make live-check` | Not a check: the one run against TJ's own accounts ([below](#the-live-check)) |
| `make live-cleanup` | Not a check: deletes what `make live-check` made, and its saved Garmin token |
| `make live-check-hevy` | Not a check: `make live-check`'s Hevy reads alone, with no Garmin sign-in ([below](#the-live-check)) |
| `make live-check-notes` | Not a check: one workout on the watch with one note of each shape the app writes and a line of symbols, with no Hevy read ([below](#the-live-check)) |

## The live check

`scripts/live_check.py` records the shapes of Hevy's and Garmin's real replies, so the fakes in `tests/fixtures.py` can follow them (spec D-10; they go into `tests/data/recorded_shapes.json`, below), and checks what the fakes can't know: how Garmin stores a repeat group, how many steps it takes in one workout, and what a recorded set looks like. TJ runs it by hand, from a clone, with his OK each time. CI never does.

1. `make live-check`. It asks for the Hevy API key, then for a Hevy `auth2.0-token` cookie copied from a private window (Enter skips Hevy Trainer), unless `HEVY_API_KEY` and `HEVY_SESSION` are set. Then it asks for the Garmin email, password and 2FA code, once: one Garmin sign-in, its own session, never the pod's token.
2. It reads Hevy. With the cookie, it prints for each Hevy Trainer template whether each of its `edits` (an exercise swapped in the Hevy app) is already in its exercises, and how many minutes ago the program last changed; no id, title or date. It also reads `user_key_values`, Hevy's per-user store, which held interface settings and no swap "for this workout only" on 2026-11-11 ([DATA.md](DATA.md)), and lists each entry's key name, value type and, for a value holding JSON, that JSON's shape. For a key that names Trainer, a workout, an exercise or a swap it adds whether the program's template ids, its exercise ids, or an exercise id not in the program occur in the value. Ids and the username in a key name show as `<id>`, and a refusal there is noted without stopping the run. Then it makes `HGS check set` in Garmin: one set of `HYPEREXTENSION` / `HYPEREXTENSION` for 10 reps with no weight, three matching curl sets, which become a repeat group, and a two-round superset, which becomes another. It reads it back, prints the exercise sent and the one Garmin stored for each set and the kinds of step Garmin stored, groups and the steps inside them included, then puts it on today and sends it to the watch.
3. It probes Garmin's step cap with `HGS check steps`: 250 steps that no repeat group can shorten, made and deleted at once, never scheduled or sent. If Garmin refuses it, it prints Garmin's status and reason, then tries 100 steps, then 50, and stops at the first size Garmin takes.
4. Everything lands in `live-check/` in the clone, which git and Docker builds ignore: `recorded.json` (shapes, Garmin's exercise keys and the probe's results, no values), `created.json` (the ids of the workouts it made) and the Garmin token. The token is never printed.
5. Start `HGS check set` on the watch, do its first set without changing the reps, and save the activity. Look at that set in Garmin Connect and on Strava: what each calls it, and whether its reps are the planned 10 or the watch's own count.
6. Then `make live-cleanup`. It removes those workouts from the calendar, deletes them and the saved token, and touches nothing else. The recorded activity stays. Running it twice is safe.

If `make live-check` stops partway, it says how many check workouts it left; `make live-cleanup` removes them, a step probe included. The script's docstring lists what it will never do.

`make live-check-hevy` is the Hevy part of steps 1 and 2 alone: it asks for the same key and cookie, reads Hevy, prints the same Trainer edit lines, and writes `live-check/recorded-hevy.json`. It signs in to nothing else, makes nothing, never touches `recorded.json`, and runs even when an earlier `make live-check` wasn't cleaned up. With no routines in the account, the exercise template and its history come from a logged workout instead.

`make live-check-notes` checks each set's note as the app writes it (spec F-30). It asks for the Garmin sign-in only, reads nothing from Hevy, and makes `HGS check notes` with the app's own `workout.build`. The numbers are made up.

1. Chest Supported Dumbbell Row, Hevy's Seal Row (Dumbbell): a warm-up and a Normal Set, both 4-6 reps, so the warm-up's rep target and the `Hevy:` line show.
2. Lying Dumbbell Pullover To Extension: a Failure Set of 8 at `17.5 lbs`.
3. Dumbbell Hammer Curl: a Drop Set of 8-12 with no weight.
4. Plank: a timed set, `0:30`.
5. Crunch: a Normal Set whose note ends with a line of symbols (`×`, `•`, `→`, `✓`, `°`, `½`, `★`, `♥`, `⚠`, two emoji and others), to see which ones the watch draws.

It reads the workout back and says whether Garmin stored every note whole. Then it puts the workout on today, sends it to the watch and prints the notes. Start it on the watch, photograph each note, and discard the activity. Then `make live-cleanup`, as after `make live-check`. It won't run while an earlier run's `live-check/created.json` is there.

## Tests

- Every change ships with tests. Coverage aims at 100% of lines and branches, CI reports it, and a gap gets a test or a written reason. A test asserts on behaviour; one that only runs a line is deleted.
- `unittest` and `unittest.mock`. No test touches the network or a real account.
- Fakes come from one module, `tests/fixtures.py`: a fake Hevy public API, a fake Hevy private API and a fake Garmin, answering in the shapes the real services answer in, with every name, id and token made up (spec D-10). They build on the preview's accounts in `src/hevy_garmin_sync/preview.py` (W-10), and add a record of every call and the ability to fail the way the real service fails. A shape or a builder changes in `preview.py`. A test never builds its own fake.
- Time is fixed: tests pin the clock and the time zone. The pinned dates live in `tests/fixtures.py`; a test spells its own only when the date is the point, such as a clock change or the Hevy Trainer cases checked against the app.
- `tests/test_exercise_data.py` checks both exercise tables against `src/hevy_garmin_sync/data/garmin_exercises.json`, the keys of Garmin's own exercise list, which ships in the package so the app can check `CUSTOM_EXERCISE_MAP` too. A row naming an exercise Garmin doesn't have fails it. It reads Hevy's muscle groups and equipment from `tests/data/hevy_api.json`. Both copies are written by `make upstream-update`; don't edit them by hand.
- `tests/test_recorded_shapes.py` runs the live check over the fakes and compares what it records with `tests/data/recorded_shapes.json`, the shapes the live checks recorded (keys and types, no values). A fake that drifts from a real reply fails it, naming the field. When a new live check records a reply differently, put its shape from the live check's file in place of the old one, and fix whatever builder the test then names.
- A test that reads files fails when it can't find them, instead of skipping.
- The chart's checks are helm-unittest suites in `charts/hevy-garmin-sync-helm/tests/`, and the image's are container-structure-test checks in `tests/structure-test.yaml`. yggdrasil's modules run both (its record 0060). Never a shell script of `grep` or `docker run` in a workflow; a check neither tool can hold goes to TJ first.
