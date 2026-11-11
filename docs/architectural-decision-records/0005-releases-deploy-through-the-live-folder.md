# 0005. Since the cutover, every release bumps the live Kubernetes-Manifests folder and so deploys

- Status: Accepted. Supersedes 0004
- Date: 2026-11-10
- Decider: TJ ("im ready to decomission the first app and go live whenever")
- Issues and PRs: #1, #16, KM#1965, KM#1969
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), Rules, "Every release deploys to TJ's cluster"

## Context

Record 0004 kept the bump in a disabled folder so the app could not start next to hevy2garmin. On 2026-11-10 TJ removed hevy2garmin and hevy-trainer-sync from the cluster (KM#1965) and turned this app on (KM#1969), which renamed the folder.

## Decision

`release.yml`'s `Bump Kubernetes-Manifests` job edits `misc/hevy-garmin-sync/kustomization.yml`. The folder is live, so the self-merging bump PR is a deploy: Argo CD rolls the pod to each new release.

## Evidence

- 2026-11-10: a run from a clone against TJ's accounts created four Garmin workouts with no failure, and Trainer's 12 weights matched hevy-trainer-sync's.
- 2026-11-10: the 0.2.0 release bumped the disabled folder, the last one to do so.

## Alternatives rejected

- **Keep the bump in a disabled folder and deploy by hand**: record 0004's arrangement, only ever meant to last until the cutover.

## Consequences

A merge to main reaches TJ's watch within minutes, with no second approval. One replica and the `Recreate` strategy keep two pods from sharing the rotating Garmin token during a roll (spec D-4). A release that breaks the app is fixed by the next release, not by a rollback in Kubernetes-Manifests, which the following bump would overwrite.
