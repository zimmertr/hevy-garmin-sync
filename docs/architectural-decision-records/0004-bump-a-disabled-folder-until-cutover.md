# 0004. Releases bump a disabled Kubernetes-Manifests folder until TJ's cutover

- Status: Superseded by 0005
- Date: 2026-11-07
- Decider: TJ ("Create the folder now")
- Issues and PRs: #1, KM#1944
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), Rules, "Releases bump a disabled Kubernetes-Manifests folder"

## Context

Every release bumps the chart version in Kubernetes-Manifests, and the file it edits must exist before the first release. The misc ApplicationSet deploys every folder under `misc/`, so a live folder would start the app next to hevy2garmin before TJ switches over.

## Decision

The bump edits `misc/hevy-garmin-sync.disabled/kustomization.yml`. The ApplicationSet skips `*.disable*` folders, and Renovate already ignores them. At cutover the folder loses `.disabled`, gains its values and resources, and `release.yml`'s bump path follows.

## Evidence

Kubernetes-Manifests `misc/applicationset.yml` excludes `misc/*.disable*`, and `.github/renovate.json` ignores `*/*.disabled/*` (read 2026-11-07).

## Alternatives rejected

- **No bump until cutover**: TJ chose to have it work from the first release.

## Consequences

The cutover changes two repos together: the folder's name and `release.yml`'s path.
