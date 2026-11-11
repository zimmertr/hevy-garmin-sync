# CI/CD

How a change gets from a PR to a release. Every workflow calls a zimmertr/yggdrasil module where one exists (record [0002](architectural-decision-records/0002-ci-on-yggdrasil-modules.md)); the module pins are the versions hevy-trainer-sync runs, and Dependabot moves them once a yggdrasil release is three days old.

```mermaid
flowchart LR
  pr["PR"] --> checks["Required checks"]
  checks -->|squash merge| main["main"]
  main --> test["test<br/>(the squash commit)"]
  test --> release["yggdrasil release module<br/>version, image amd64+arm64,<br/>scan, tag, GitHub release"]
  release --> chart["Publish OCI chart<br/>(same version)"]
  chart --> bump["Bump Kubernetes-Manifests<br/>self-merging PR"]
```

## PR checks

| Workflow | Check | What it does |
|---|---|---|
| `test.yml` | `test` | The suite under coverage, with the line and branch table in the run summary |
| `pr.yml` | `Python Lint` | ruff and mypy, from the hashed dev lock |
| `pr.yml` | `Chart` | `helm lint`, and the chart rendered with the defaults and with an existing Secret |
| `pr.yml` | `Docker Build / Docker Build` | yggdrasil's docker-build module: hadolint, the amd64 image built, a Trivy table in a sticky comment, the smoke test, and a failure on any fixable Critical or High |
| `lint.yml` | `Lint / actionlint`, `Lint / zizmor`, `Lint / semgrep` | yggdrasil's lint module over the workflows and the Dockerfile |
| `pr-title.yml` | `PR Title / PR Title` | yggdrasil's pr-title module: the title must be `type(scope): summary` |
| `dependabot-auto-merge.yml` | `Dependabot auto-merge / Auto-merge patch and minor updates` | Arms auto-merge on Dependabot's patch and minor updates; skipped on every other PR |

The default-branch ruleset requires every check above except the auto-merge one. Renaming or adding a check needs a PR in zimmertr/yggdrasil that changes this repo's `required_checks`, merged together with the rename; otherwise PRs wait forever on the old name.

## The release

Every merge to main is a release (`release.yml`), one at a time:

1. `test` runs again on the squash commit.
2. yggdrasil's release module reads the version from the squash commit's title with GitVersion (`feat` a minor, `!` a major, anything else a patch; the first release is 0.1.0), builds and pushes `ghcr.io/zimmertr/hevy-garmin-sync:<version>` for amd64 and arm64 with an SBOM and provenance, scans each platform with Trivy, then tags `v<version>` and publishes the GitHub release. A fixable Critical or High stops the tag and release.
3. `Publish OCI chart` writes the image's digest into `values.yaml`, packages `charts/hevy-garmin-sync-helm` with that version as both `version` and `appVersion`, and pushes it to `oci://ghcr.io/zimmertr`. A re-run finds it there and skips. Record: [0006](architectural-decision-records/0006-ghcr-and-a-digest-pinned-chart.md)
4. `Bump Kubernetes-Manifests` sets the chart version in `misc/hevy-garmin-sync/kustomization.yml` through a PR on the fixed branch `chore/hevy-garmin-sync-chart`, and arms auto-merge. When that PR merges, Argo CD rolls the pod to the new release.

`image-scan.yml` re-scans the latest release every Monday and sends the findings to the Security tab. Its first run fails until a release exists.

## The upstream check

`upstream-check.yml` runs every Monday and can be started by hand. It is not a required check, and no yggdrasil module covers it, so it lives here. It runs `scripts/check_upstream.py`, which reads two public files with no sign-in and compares them with their copies in `tests/data`:

| Source | Copy | Keeps |
|---|---|---|
| Garmin's exercise list, `https://connect.garmin.com/web-data/exercises/Exercises.json` | `garmin_exercises.json` | Each category key with its exercise keys (spec F-51) |
| Hevy's API spec, inside `https://api.hevyapp.com/docs/swagger-ui-init.js` | `hevy_api.json` | Each path with its methods, and the exercise type, equipment, muscle group and set type enums |

1. `Compare` runs the script. The same copies pass and open nothing. A source it can't fetch or read fails the run.
2. On a difference, `Issue` opens an issue titled "Garmin's exercise list or Hevy's API changed", labelled `P2`, `enhancement` and `ci`, with what was added and removed. While that issue is open, a later run comments on it instead of opening another.
3. `PR` reads the sources again, rewrites the copies and opens a PR from the fixed branch `chore/upstream-copies`, or force-pushes the one already open. Its title is `test(upstream): update the copies of Garmin's exercise list and Hevy's API`, and it closes the issue. It uses `GH_PAT`, because a PR opened with `GITHUB_TOKEN` starts no workflows and its required checks would never report. When this job fails, the issue stays and the run fails.

Record: [0010](architectural-decision-records/0010-a-weekly-check-of-the-upstream-copies.md)

After a failure, re-run the failed jobs only. Never re-run an old release after a newer one shipped.

## Secrets

| Secret | Store | Used by |
|---|---|---|
| `GITHUB_TOKEN` | Given to each run | The image push and the chart push, to GHCR (`packages: write`); the upstream check's issue (`issues: write`) |
| `GH_PAT` | Actions | The Kubernetes-Manifests bump, and the upstream check's push and PR here (contents and pull-requests write on both repos) |
| `AUTO_MERGE_PAT` | Dependabot | The auto-merge module's `merge-token`; a merge made with `GITHUB_TOKEN` would not start the release |

## Repo settings

Since 2026-11-10 the repo's settings, rulesets and required checks are applied by Terraform from zimmertr/yggdrasil (`repos/zimmertr/hevy-garmin-sync.yml` there, plus its repo module). A setting changed by hand is put back by the next apply, so a settings change is a yggdrasil PR that TJ okays first.

Before the import, these were set by API with TJ's okay, and Terraform took them over unchanged:

| Date | Setting |
|---|---|
| 2026-11-07 | Squash merge only, title and body from the PR; auto-merge on; head branches deleted; "Update branch" on; wiki off |
| 2026-11-07 | Secret scanning and push protection; Dependabot alerts and security updates; private vulnerability reporting; immutable releases |
| 2026-11-07 | Actions must be pinned by full commit SHA; CodeQL default setup; rulesets "default branch" (PR required, 0 approvals, stale reviews dismissed, threads resolved, squash only, no force push or deletion) and "release tags" (`refs/tags/v*`: no update or deletion) |
| 2026-11-10 | The eight required checks on the "default branch" ruleset; Projects off |
