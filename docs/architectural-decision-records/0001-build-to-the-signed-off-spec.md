# 0001. Build hevy-garmin-sync to the signed-off spec, one direction only, in one repo with its chart

- Status: Accepted
- Date: 2026-11-07
- Decider: TJ ("Spec LGTM", 2026-11-07, after an interview and live watch tests)
- Issues and PRs: #1
- Cited in code as: #1
- Guide: [`CLAUDE.md`](../../CLAUDE.md), Rules, "Build to the spec"

## Context

hevy-trainer-sync mirrored Hevy Trainer into Hevy routines so hevy2garmin could put them on the watch, and hevy2garmin merged Hevy's sets into Garmin activities after the session. Strava keeps whatever the watch recorded first, so only the planned workout on the watch decides what Strava shows. TJ found the result hard to run and wanted something any Hevy and Garmin user could set up.

## Decision

A new app, built to [SPEC.md](../SPEC.md): Hevy routines (and Hevy Trainer workouts, when signed in) become Garmin strength workouts, scheduled and sent to the watch. It reads Hevy, writes Garmin, and never calls Strava. One repo holds the app and its Helm chart. The spec is the source of truth and changes with every decision.

## Evidence

Live tests on TJ's Fenix 8 on 2026-11-07 settled how weights, repeats, notes, rests and timed sets show on the watch; each is recorded in the spec with its date.

## Alternatives rejected

- **Forking hevy2garmin**: it is built around merging after the session, which Strava never sees.
- **Editing Strava**: its API can't edit exercises or delete activities, and its terms forbid reverse-engineering its app.
- **Garmin's official APIs**: the personal key is read-only, and the Training API needs business access.
- **An organization with separate app and chart repos**: dropped by TJ on 2026-11-07 for one repo.

## Consequences

Every requirement carries an ID in the spec, and code, tests and PRs cite it. hevy-trainer-sync is archived after the cutover (spec D-7).
