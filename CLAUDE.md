# hevy-garmin-sync

Turns Hevy routines, and optionally Hevy Trainer's workouts, into Garmin Connect strength workouts and sends them to the watch. One Python process in one Docker image, configured by environment variables. [`docs/SPEC.md`](docs/SPEC.md) is the signed-off plan and the source of truth for scope and behaviour; start with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for which module does what.

## Documentation

Prose lives in `docs/`. A change that makes any page untrue updates it in the same PR. The README is TJ's: keep it accurate and in his voice, never restructure it, and change its variable list together with `docs/CONFIGURATION.md`.

| Doc | Holds |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | The signed-off spec: every requirement by ID, the open items, the backlog |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The repo's layout, one run step by step, the modules, the exercise map, the image and the chart |
| [`docs/HEVY_TRAINER_RULES.md`](docs/HEVY_TRAINER_RULES.md) | Hevy Trainer's rules as findings: the week, weights, rounding, warm-ups, rep ranges, and the cases checked against the Hevy app |
| [`docs/CICD.md`](docs/CICD.md) | From PR to release, with the diagram, the required checks, the secrets and where the repo's settings live |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | Every variable and chart value, and where each is set |
| [`docs/USAGE.md`](docs/USAGE.md) | What TJ sees, and what to do when it breaks |
| [`docs/DATA.md`](docs/DATA.md) | Each upstream service, its terms, and every quirk found, dated |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | The CI-first loop, the `make` targets, how to write tests |
| [`docs/SBOM.md`](docs/SBOM.md) | Where each release's bill of materials is |
| [`docs/architectural-decision-records/`](docs/architectural-decision-records/README.md) | One record per decision. The README is the index and says how to write one |

## Rules

- **Build to the spec.** Every requirement has an ID in `docs/SPEC.md`; cite it in code, tests and PRs, and update the spec in the same PR when a decision changes. One direction only: Hevy is read, Garmin is written, Strava is never called. Record: [0001](docs/architectural-decision-records/0001-build-to-the-signed-off-spec.md)
- **CI runs on yggdrasil's modules.** Never write a check from scratch that a zimmertr/yggdrasil module covers; a check two repos need belongs in yggdrasil. Record: [0002](docs/architectural-decision-records/0002-ci-on-yggdrasil-modules.md)
- **The image and the chart are in GHCR**, under `ghcr.io/zimmertr`, pushed with each job's own token, and the chart pins the image's digest. The chart is `hevy-garmin-sync-helm`, never the image's name. Record: [0006](docs/architectural-decision-records/0006-ghcr-and-a-digest-pinned-chart.md)
- **Every release deploys to TJ's cluster.** The release bumps the chart version in Kubernetes-Manifests `misc/hevy-garmin-sync`, and Argo CD rolls the pod. Record: [0005](docs/architectural-decision-records/0005-releases-deploy-through-the-live-folder.md)
- **The repo is public.** No tokens, ids or personal data in code, fixtures, logs or docs. The Hevy Trainer rules are written down as findings only, not how they were found (spec D-7b).
- **Live calls need TJ's okay**, each time, and TJ runs any sign-in himself.
- **Exercise names are data.** A wrong Garmin exercise is fixed in `src/hevy_garmin_sync/data/exercise_map.csv` (or `custom_exercise_map.csv`), never in code, and every row must name a pair in `tests/data/garmin_exercises.json` (spec F-51, F-54).

## Tests

Every change ships with tests. Coverage aims at 100% of lines and branches; CI reports it, and a gap gets a test or a written reason. Tests use `unittest` and `unittest.mock`, build every fake in one fixtures module, pin the clock and time zone, and never touch the network. Details: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Issues

File issues with the `create-issue` skill from zimmertr/ai-config: the two-sentence summary, the six sections, the hemingway and humanizer passes, one priority, one type, the area labels and the session label. The skill reads the four things below from this section.

- **The reader**: a lifter who uses Hevy and a Garmin watch and doesn't read code.
- **The gates**: `test` (aim 100% coverage), `Python Lint` (ruff and mypy), `Chart`, `Lint / actionlint`, `Lint / zizmor`, `Lint / semgrep`, `PR Title / PR Title`, and `Docker Build / Docker Build` (the image built, scanned by Trivy and smoke-tested).
- **The constraints**: never write to Hevy; only touch Garmin workouts the app owns; no tokens, ids or personal data in the repo; nothing Docker-specific; the spec (`docs/SPEC.md`, issue #1) is the source of truth.
- **The areas**: `hevy`, `trainer`, `garmin`, `watch`, `calendar`, `exercise-map`, `config`, `ci`, `docs`, `helm`.

## Working in this repo

- Work in a fresh clone in the session's scratchpad, never in TJ's checkout. Branch from the latest `origin/main`.
- Everything reaches main through a squash-merged PR that TJ approves. Never push to main.
- The PR title is `type(scope): summary`; it picks the release version, and every merge to main is a release.
- CI builds and pushes the image and the chart; never build or push one by hand.
- Actions are pinned to full commit SHAs with the version in a comment; the repo refuses anything else.
