# 0021. CI takes yggdrasil v3: one images list, signed provenance, and the new checks

- Status: Accepted. Supersedes 0012 in part: the `Makefile` takes Helm from the helm-unittest image
- Date: 2026-11-21
- Decider: TJ, 2026-11-21, in zimmertr/yggdrasil#133, which moves every repo onto its v3 modules.
- Issues and PRs: zimmertr/yggdrasil#133, zimmertr/yggdrasil#141
- Cited in code as: none
- Guide: [`docs/CICD.md`](../CICD.md)

## Context

zimmertr/yggdrasil v3.0.0 changed two modules this repo calls. `docker-build` now takes the release module's `images` list, and the release module attests every image and chart it pushes, which needs two more permissions. v3 also added a cache-cleanup, a dependency-review and a scorecard module, and two lint checks.

## Decision

- Every module call pins v3.0.1.
- `pr.yml` gives `docker-build` the release's image, with `tests/structure-test.yaml` in its entry. Its check is `Docker Build / Docker Build (zimmertr/hevy-garmin-sync)`.
- `release.yml` grants `attestations: write` and `id-token: write`, so the image and the chart carry GitHub's signed build provenance.
- `pr.yml` runs `Dependency Review`, `cache-cleanup.yml` deletes a closed PR's caches, and `scorecard.yml` runs OpenSSF Scorecard weekly and on push to main.
- The `Makefile`'s `make chart` lints and renders with the Helm inside the helm-unittest image it already pins, and `alpine/helm`, an unofficial rebuild of Helm, is gone.

## Evidence

- 2026-11-21, zimmertr/yggdrasil#133: `alpine/helm` was the riskiest image left after the release module moved to official Helm, and it was used only here.
- 2026-11-21: `helmunittest/helm-unittest:4.3.0-1.2.1` runs `helm version` as v4.3.0.
- 2026-11-21: this repo had no shellcheck or docs findings under the new lint checks.

## Alternatives rejected

- Keep `alpine/helm` for `make chart`: a second Helm image from a source with no tie to Helm's project, when the pinned helm-unittest image already carries Helm.

## Consequences

- `make chart` runs Helm v4.3.0, the version inside the helm-unittest image, while CI's chart module installs the version yggdrasil pins, v4.3.2 on 2026-11-21. They move together only when Renovate bumps the helm-unittest image.
- The required checks change in zimmertr/yggdrasil's `repos/zimmertr/hevy-garmin-sync.yml`, in the same pass as this PR.
