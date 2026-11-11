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
| `make chart` | `helm lint` and two renders, as the `Chart / Chart` check does |
| `make build` | The image, tagged `hevy-garmin-sync:dev` |
| `make scan` | The release scan's rules against that build |
| `make lock` | Not a check: recompiles `requirements.txt` and `requirements-dev.txt` from the `.in` files, hashed. A pin change ships with its lock in the same PR |
| `make upstream-check` | Not a check: the weekly upstream check ([CICD.md](CICD.md#the-upstream-check)). Reads Garmin's exercise list and Hevy's published API spec and prints what differs from the repo's copies of them. Exits 3 on a difference and 2 when a source can't be read |
| `make upstream-update` | Not a check: the same, then rewrites the copies that differ |
| `make live-check` | Not a check: the one run against TJ's own accounts ([below](#the-live-check)) |
| `make live-cleanup` | Not a check: deletes what `make live-check` made, and its saved Garmin token |
| `make live-check-hevy` | Not a check: `make live-check`'s Hevy reads alone, with no Garmin sign-in ([below](#the-live-check)) |

## The live check

`scripts/live_check.py` records the shapes of Hevy's and Garmin's real replies, so the fakes in `tests/fixtures.py` can follow them (spec D-10; they go into `tests/data/recorded_shapes.json`, below), and puts check workouts on the watch for #22, #24 and #6. TJ runs it by hand, from a clone, with his OK each time. CI never does.

1. `make live-check`. It asks for the Hevy API key, then for a Hevy `auth2.0-token` cookie copied from a private window (Enter skips Hevy Trainer), unless `HEVY_API_KEY` and `HEVY_SESSION` are set. Then it asks for the Garmin email, password and 2FA code, once: one Garmin sign-in, its own session, never the pod's token.
2. It reads Hevy, then makes `HGS check names` and `HGS check 1` to `HGS check 6` in Garmin, and last `HGS check step name`, one step with a `stepName` and no exercise. Garmin may refuse that last one; the script then says so and carries on with the other seven. It puts every workout it made, seven or eight, on today and sends them to the watch. It prints the exercise sent and the one Garmin stored for each step of `HGS check names` and `HGS check step name`, then everything it recorded. If Garmin stores the steps nested another way than the app reads them, it also lists every step it finds in the stored workout.
3. Everything lands in `live-check/` in the clone, which git and Docker builds ignore: `recorded.json` (shapes and Garmin's exercise keys, no values), `created.json` (the ids of the workouts it made) and the Garmin token. The token is never printed.
4. Look at the watch, then `make live-cleanup`. It removes those workouts from the calendar, deletes them and the saved token, and touches nothing else. Running it twice is safe.

If `make live-check` stops partway, it says how many workouts it made; `make live-cleanup` removes them. The script's docstring lists what it will never do.

`make live-check-hevy` is step 1 alone: it asks for the same key and cookie, reads Hevy, and writes `live-check/recorded-hevy.json`. It signs in to nothing else, makes nothing, never touches `recorded.json`, and runs even when an earlier `make live-check` wasn't cleaned up. With no routines in the account, the exercise template and its history come from a logged workout instead.

## Tests

- Every change ships with tests. Coverage aims at 100% of lines and branches, CI reports it, and a gap gets a test or a written reason. A test asserts on behaviour; one that only runs a line is deleted.
- `unittest` and `unittest.mock`. No test touches the network or a real account.
- Fakes come from one module, `tests/fixtures.py`: a fake Hevy public API, a fake Hevy private API and a fake Garmin, answering in the shapes the real services answer in, with every name, id and token made up (spec D-10). Each can be told to fail the way the real service fails. A test never builds its own fake.
- Time is fixed: tests pin the clock and the time zone. The pinned dates live in `tests/fixtures.py`; a test spells its own only when the date is the point, such as a clock change or the Hevy Trainer cases checked against the app.
- `tests/test_exercise_data.py` checks both exercise tables against `src/hevy_garmin_sync/data/garmin_exercises.json`, the keys of Garmin's own exercise list, which ships in the package so the app can check `CUSTOM_EXERCISE_MAP` too. A row naming an exercise Garmin doesn't have fails it. It reads Hevy's muscle groups and equipment from `tests/data/hevy_api.json`. Both copies are written by `make upstream-update`; don't edit them by hand.
- `tests/test_recorded_shapes.py` runs the live check over the fakes and compares what it records with `tests/data/recorded_shapes.json`, the shapes the live checks recorded (keys and types, no values). A fake that drifts from a real reply fails it, naming the field. When a new live check records a reply differently, put its shape from the live check's file in place of the old one, and fix whatever builder the test then names.
- A test that reads files fails when it can't find them, instead of skipping.
