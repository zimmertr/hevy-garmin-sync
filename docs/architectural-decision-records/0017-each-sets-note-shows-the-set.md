# 0017. Each set's note shows the set as the watch's set-info screen does, with Hevy's name when Garmin's differs

- Status: Accepted. Supersedes 0015 in part
- Date: 2026-11-13
- Decider: TJ, after an arm day with the notes of 0015, in the session that opened #64
- Issues and PRs: #64, #65
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-30, F-30b, F-22 and C-12 in [`docs/SPEC.md`](../SPEC.md)

## Context

During a workout the watch shows the set's weight and reps on a set-info screen that is only reached by opening the step list, which is slow on a watch. The note is one page down from the set's main screen. Under 0015 it held last time's sets, and during the warm-ups it held only `Warm-up`. Seal Row (Dumbbell) showed on the watch as Chest Supported Dumbbell Row, Garmin's closest name, with nothing to say it was the same lift.

## Decision

Each set's note is the set type in Hevy's words, the target, the weight, and Hevy's exercise name when Garmin's name has a word Hevy's doesn't, each on a line of its own: `Warm Up Set` / `4-6 Reps` / `35 lbs` / `Hevy: Seal Row (Dumbbell)`. Last time's sets leave the note and stay on the status page. A Hevy Trainer warm-up gets the working sets' rep range, as the Hevy app shows it.

## Evidence

- 2026-11-13, TJ's Fenix 8: the warm-up note read `Warm-up` alone, while the set-info screen showed `Chest Supported Dumbbell Row` / `6 Reps` / `50.0 lbs`.
- 2026-11-13, the Hevy app: Goblet Squat's two warm-ups showed the same `4-6` as its three working sets.
- 2026-11-13, the exercise map: of 455 built-in exercises, 239 get the Hevy line under the word rule; under exact word matching it would have been 341.

## Alternatives rejected

- Keeping last time's sets in the note (0015): during a set the lifter wants what to do now, and the Hevy app shows history better than the watch can.
- Removing the note: a working set would then have no screen with its weight short of the step list.
- The Garmin exercise name in the note: the watch shows it at the start of each set.
- `Hevy Name:` as the label: `Hevy:` is shorter, and the line wraps anyway.

## Consequences

`tests/test_workout.py` pins every note shape, and `make live-check-notes` puts each on the watch. Matching sets now always get matching notes, so they share a repeat group again. A saved workout no longer changes any note, so it no longer rewrites Garmin workouts.
