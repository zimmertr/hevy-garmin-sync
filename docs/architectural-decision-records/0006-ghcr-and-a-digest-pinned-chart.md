# 0006. The image and the chart are in GHCR, and the chart pins the image's digest

- Status: Accepted. Supersedes 0003
- Date: 2026-11-10
- Decider: TJ, 2026-11-10, on zimmertr/yggdrasil#9: hevy-garmin-sync moves first, and "LGTM" to the chart pinning the image's digest.
- Issues and PRs: zimmertr/yggdrasil#9
- Cited in code as: record 0006, in `.github/workflows/release.yml`
- Guide: [`docs/CICD.md`](../CICD.md)

## Context

0003 put the image and the chart on Docker Hub until yggdrasil's release module could push to GHCR. Its v1.0.0 does, with each job's own `GITHUB_TOKEN`, and yggdrasil's record 0052 pins deploys by digest, because a GHCR tag can be moved. This repo's image ships inside its chart, so no deploy file names the image for a digest to go next to.

## Decision

- The image is `ghcr.io/zimmertr/hevy-garmin-sync`, pushed by yggdrasil's release module v1.0.0. The chart is `ghcr.io/zimmertr/hevy-garmin-sync-helm`, pushed by the `chart` job with `GITHUB_TOKEN`. Both jobs grant `packages: write`, and the Docker Hub secrets are no longer used.
- Before packaging, the `chart` job reads the image's digest from GHCR and writes it to `image.digest` in `values.yaml`. The Deployment then runs `image@digest`, the bytes the release scanned. With `image.digest` empty, it uses the tag, as before.

## Evidence

- 2026-11-10, yggdrasil's probe (zimmertr/yggdrasil#73): GHCR takes a second push of the same tag or chart version, and `GITHUB_TOKEN` with `packages: write` pushes both.
- The chart job's `helm show chart` check skips a version already in GHCR, so a re-run never re-pushes it.

## Alternatives rejected

- The tag only: someone with write access could move it, and every install would follow.
- A digest set in Kubernetes-Manifests' `valuesInline`: one more path for each release's bump to write, and a `helm install` outside the cluster would still pull by tag.

## Consequences

- Each chart version pins one image. Running another means setting `image.digest` to empty and `image.tag`.
- The Docker Hub image and chart stay until zimmertr/yggdrasil#9 step 7.6, so a rollback can still pull them.
