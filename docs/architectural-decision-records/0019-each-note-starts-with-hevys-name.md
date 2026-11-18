# 0019. Each set's note starts with Hevy's name for the exercise

- Status: Accepted. Supersedes 0017 in part
- Date: 2026-11-17
- Decider: TJ, after a leg day, in the session that closed #64
- Issues and PRs: #64, #101
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-30 in [`docs/SPEC.md`](../SPEC.md)

## Context

Under 0017 a note named the exercise last, as `Hevy: Seal Row (Dumbbell)`, and only when Garmin's name had a word Hevy's didn't. So most notes didn't say which lift they were for, and the name sat at the bottom. TJ asked for the exercise name first, in bold and ideally smaller, and for Hevy's name in place of Garmin's on the watch.

## Decision

Every note's first line is Hevy's name for the exercise, in plain letters. The set type, the target and the weight follow, each on its own line. The `Hevy:` line and the word comparison behind it are gone.

## Evidence

- 2026-11-10, TJ's Fenix 8: Garmin accepted a step with a `stepName`, kept no `stepName`, and the watch showed the category's name (`docs/DATA.md`). So Hevy's name can't replace Garmin's on the watch's own screens.
- 2026-11-17, TJ's photos: a note's lines are all one size, and a note has no markup.
- 2026-11-17, TJ's Fenix 8, `make live-check-notes`: the name in Unicode's sans-serif bold letters showed as a diamond with a question mark for each letter.

## Alternatives rejected

- Hevy's name in the step, in place of Garmin's: Garmin drops it (2026-11-10).
- No Garmin exercise at all, so the watch shows something generic: the watch would show only a category such as "Lunge", and Garmin Connect and Strava would lose the exercise.
- The name in Unicode's bold letters: tried, and the watch can't draw them (2026-11-17).
- A smaller font: a note has none to set.

## Consequences

`tests/test_workout.py` pins the first line, and `make live-check-notes` puts one of each note on the watch. Every workout's notes change, so every Garmin workout is rewritten once.
