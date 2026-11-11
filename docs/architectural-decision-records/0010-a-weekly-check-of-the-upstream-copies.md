# 0010. A weekly check compares Garmin's exercise list and Hevy's API spec with their copies, and on a difference opens one issue and one PR

- Status: Accepted
- Date: 2026-11-10
- Decider: TJ, 2026-11-10, on #26: "Open an issue and attempt to also open a PR", and for the PR's token, "Lets reuse GH_PAT".
- Issues and PRs: #26, #36
- Cited in code as: #26 and record 0010, in `scripts/check_upstream.py`, `.github/workflows/upstream-check.yml` and `tests/test_exercise_data.py`
- Guide: [`docs/CICD.md`](../CICD.md), "The upstream check"

## Context

The tests check every exercise map row against `tests/data/garmin_exercises.json`, a copy of the keys of Garmin's exercise list, and hard-coded the values of Hevy's enums. Nothing read either source again, so a renamed or removed Garmin exercise passed CI and showed up as a wrong name on the watch, and a change to Hevy's API, such as a routine feed (spec F-2), went unseen. hevy2garmin, the tool this app replaced, ran a weekly job against Hevy's spec that failed when the spec couldn't be fetched.

## Decision

- `scripts/check_upstream.py`, standard library only, reads the two public files with a generic `User-Agent` and no token or cookie, reduces each to a small copy in `tests/data`, and compares. Garmin's copy is each category key with its exercise keys. Hevy's (`hevy_api.json`) is each path with its methods and four enums: exercise type, equipment, muscle group and set type. Only those, since the spec's descriptions change often and a copy of them would open an issue for nothing. It exits 0 when both match, 3 on a difference and 2 when a source can't be fetched or read; 1 stays Python's own exit on a crash, so a bug never reads as a difference. `--write` rewrites the copies, and only when both sources were read.
- `tests/test_exercise_data.py` reads Hevy's muscle groups and equipment from `hevy_api.json`, so the values live in one place.
- `.github/workflows/upstream-check.yml` runs it every Monday at 15:37 UTC and by hand. On a difference, the `Issue` job opens one issue with `GITHUB_TOKEN` (`issues: write`), or comments on the open one with the same title. The `PR` job reads the sources again, rewrites the copies, and opens or force-pushes one PR from the fixed branch `chore/upstream-copies` with `GH_PAT`, which closes the issue. A source that can't be read fails the run.
- No new secret. `GH_PAT` already had contents and pull requests write on this repo, beside Kubernetes-Manifests.

## Evidence

- 2026-11-10, the first run (`make upstream-check`): Garmin's list matched the committed copy, 47 categories and 1,536 exercises. Hevy's spec held 14 paths under `/v1/`, and its enums are the schemas `CustomExerciseType`, `EquipmentCategory` and `MuscleGroup`, and the `type` of `PostRoutinesRequestSet`. The muscle groups and equipment were the values the test had hard-coded.
- 2026-11-10: zimmertr/yggdrasil's workflows are `auto-merge`, `checks`, `ci-docker-build`, `ci-release`, `dependabot-auto-merge`, `docker-build`, `image-scan`, `lint`, `pr-title`, `release` and the three `terraform` ones. None compares a repo's copies with an upstream source, so this one lives here (record 0002).

## Alternatives rejected

- **Fail the run and print the difference, with no issue or PR**: no token and no write permission, but nothing lands on the board (#26, option B).
- **Open the PR with `GITHUB_TOKEN`**: a PR it opens starts no workflows, so the required checks never report.
- **A new secret for the PR**: `GH_PAT` already reaches the repo with the access the PR needs. The token audit, zimmertr/yggdrasil#12, moves every user of `GH_PAT` to the yggdrasil bot App, this one included.
- **Commit the whole spec**: its descriptions and examples change without the API changing.
- **Hevy's own exercise list**: it needs an API key, and spec F-55 covers a new Hevy exercise at runtime.

## Consequences

- `CommittedCopiesTest` in `tests/test_check_upstream.py` fails when a copy is not in the format `--write` writes, so a rewrite shows only real changes.
- The issue and PR steps cannot run before merge: a scheduled workflow runs only from main. The first manual run after merge proves them.
- The PR job force-pushes its branch while a difference stays, so a commit added to that branch by hand is lost unless the PR merges before the next run.
- A merged copy update is a release like any other, and rolls TJ's pod.
- One more user of `GH_PAT`, to move to the App with the rest.
