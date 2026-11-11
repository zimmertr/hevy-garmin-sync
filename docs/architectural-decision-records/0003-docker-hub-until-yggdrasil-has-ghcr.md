# 0003. The image and the chart are published to Docker Hub until yggdrasil adds GHCR

- Status: Superseded by [0006](0006-ghcr-and-a-digest-pinned-chart.md)
- Date: 2026-11-07
- Decider: TJ ("Docker Hub for now")
- Issues and PRs: #1, zimmertr/yggdrasil#9
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), Rules, "The image and the chart are on Docker Hub"

## Context

The spec first named `ghcr.io` for the image and the chart. yggdrasil's release module logs in only to Docker Hub, and no module pushes charts.

## Decision

The image is `docker.io/zimmertr/hevy-garmin-sync`, multi-arch. The chart is named `hevy-garmin-sync-helm` and pushed to `oci://registry-1.docker.io/zimmertr` by a job copied from bluebird-helm. zimmertr/yggdrasil#9 will add GHCR and move every repo, this one included.

## Evidence

yggdrasil's `docs/CONFIGURATION.md` (2026-11-07): the release module takes `dockerhub-username` and `dockerhub-token`, and nothing else. bluebird#111 found that a chart named like its image collides on the OCI path.

## Alternatives rejected

- **A GHCR flow of our own**: yggdrasil is where it belongs, and #9 plans it.

## Consequences

Docker Hub's immutable tags are set in its web UI, per repo, by TJ.
