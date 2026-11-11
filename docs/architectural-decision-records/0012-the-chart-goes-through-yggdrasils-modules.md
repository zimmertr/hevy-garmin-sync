# 0012. The chart is checked, pushed and deployed by yggdrasil's modules

- Status: Accepted. Supersedes 0002 in part
- Date: 2026-11-11
- Decider: TJ, 2026-11-11, on zimmertr/yggdrasil#74: "C", the release module pushing the chart itself, then "LGTM" to zimmertr/yggdrasil#82.
- Issues and PRs: zimmertr/yggdrasil#74, #41
- Cited in code as: record 0012, in `.github/workflows/pr.yml` and `.github/workflows/release.yml`
- Guide: [`docs/CICD.md`](../CICD.md)

## Context

0002 kept three chart jobs in this repo, copied from bluebird-helm, because no yggdrasil module covered them: the check on PRs, the push after a release, and the Kubernetes-Manifests bump. yggdrasil v1.1.0 covers all three (its record 0054).

## Decision

- On a PR, the `Chart` job calls yggdrasil's `chart.yml`. This repo's renders go in its `test` input. The required check is `Chart / Chart`.
- On main, the release module gets `charts` and `deploys`. It pushes the chart after the tag, with `appVersion` set to the release and the image's digest in `values.yaml` (record [0006](0006-ghcr-and-a-digest-pinned-chart.md)), then opens the Kubernetes-Manifests PR (record [0005](0005-releases-deploy-through-the-live-folder.md)).
- The `Publish OCI chart` and `Bump Kubernetes-Manifests` jobs are deleted.

## Evidence

- 2026-11-11, zimmertr/yggdrasil#82: the module's dry run packaged a test chart, and its chart check passed on one.

## Alternatives rejected

- Keeping the copies: a fix to one repo's copy never reached the other.

## Consequences

- A failed chart push is finished with "Re-run failed jobs". "Re-run all jobs" finds the tag and pushes nothing, where this repo's own job would have pushed.
- Helm's version is yggdrasil's. The `Makefile`'s `HELM_IMAGE` follows it by hand.
