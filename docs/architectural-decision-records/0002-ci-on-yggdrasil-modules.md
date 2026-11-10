# 0002. CI runs on zimmertr/yggdrasil's modules, pinned to the versions a live consumer runs

- Status: Accepted
- Date: 2026-11-07
- Decider: TJ ("For CI, for example, we shouldn't be writing anything from scratch. But instead using the modules defined in yggdrasil.")
- Issues and PRs: #1
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), Rules, "CI runs on yggdrasil's modules"

## Context

TJ's repos share their CI through yggdrasil's reusable workflows. A new repo that wrote its own would drift from the rest.

## Decision

The workflows call yggdrasil's `docker-build`, `lint`, `pr-title`, `release`, `image-scan` and `auto-merge` modules. They are pinned to the commits hevy-trainer-sync runs (v0.8.1, and v0.9.2 for lint), and Dependabot moves the pins once a yggdrasil release is three days old. What no module covers stays in this repo, copied from where it already runs: the test job and the ruff and mypy job from hevy-trainer-sync, and the chart check, push and Kubernetes-Manifests bump from bluebird-helm.

## Evidence

The yggdrasil session (yggdrasil-98) confirmed the pins, inputs and secrets on 2026-11-07; no yggdrasil release was three days old that day.

## Alternatives rejected

- **The newest yggdrasil release**: v0.10.1 to v0.14.0 were all released that day, inside the three-day bake.
- **Writing the chart jobs as a new yggdrasil module**: a second repo would have to need them first.

## Consequences

Required check names follow the caller jobs; renaming a job means updating the ruleset in the same change.
