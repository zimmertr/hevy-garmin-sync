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
| `make chart` | `helm lint` and two renders, as the `Chart` job does |
| `make build` | The image, tagged `hevy-garmin-sync:dev` |
| `make scan` | The release scan's rules against that build |
| `make lock` | Not a check: recompiles `requirements.txt` and `requirements-dev.txt` from the `.in` files, hashed. A pin change ships with its lock in the same PR |
| `make upstream-check` | Not a check: the weekly upstream check ([CICD.md](CICD.md#the-upstream-check)). Reads Garmin's exercise list and Hevy's published API spec and prints what differs from the copies in `tests/data`. Exits 3 on a difference and 2 when a source can't be read |
| `make upstream-update` | Not a check: the same, then rewrites the copies that differ |

## Tests

- Every change ships with tests. Coverage aims at 100% of lines and branches, CI reports it, and a gap gets a test or a written reason. A test asserts on behaviour; one that only runs a line is deleted.
- `unittest` and `unittest.mock`. No test touches the network or a real account.
- Fakes come from one module, `tests/fixtures.py`: a fake Hevy public API, a fake Hevy private API and a fake Garmin, answering in the shapes the real services answer in, with every name, id and token made up (spec D-10). Each can be told to fail the way the real service fails. A test never builds its own fake.
- Time is fixed: tests pin the clock and the time zone. The pinned dates live in `tests/fixtures.py`; a test spells its own only when the date is the point, such as a clock change or the Hevy Trainer cases checked against the app.
- `tests/test_exercise_data.py` checks both exercise tables against `tests/data/garmin_exercises.json`, the keys of Garmin's own exercise list. A row naming an exercise Garmin doesn't have fails it. It reads Hevy's muscle groups and equipment from `tests/data/hevy_api.json`. Both copies are written by `make upstream-update`; don't edit them by hand.
- A test that reads files fails when it can't find them, instead of skipping.
