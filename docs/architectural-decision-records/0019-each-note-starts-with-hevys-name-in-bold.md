# 0019. Each set's note starts with Hevy's name for the exercise, in Unicode's bold letters

- Status: Accepted. Supersedes 0017 in part
- Date: 2026-11-17
- Decider: TJ, after a leg day, in the session that closed #64
- Issues and PRs: #64, #101
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-30 in [`docs/SPEC.md`](../SPEC.md)

## Context

Under 0017 a note named the exercise last, as `Hevy: Seal Row (Dumbbell)`, and only when Garmin's name had a word Hevy's didn't. So most notes didn't say which lift they were for, and the name sat at the bottom. TJ asked for the workout's exercise name first, in bold and ideally smaller, and for Hevy's name in place of Garmin's on the watch.

## Decision

Every note's first line is Hevy's name for the exercise, with its letters and digits in Unicode's sans-serif bold (U+1D5D4 on) and anything else as it is. The set type, the target and the weight follow, each on its own line. The `Hevy:` line and the word comparison behind it are gone.

## Evidence

- 2026-11-10, TJ's Fenix 8: Garmin accepted a step with a `stepName`, kept no `stepName`, and the watch showed the category's name (`docs/DATA.md`). So Hevy's name can't replace Garmin's on the watch's own screens.
- 2026-11-13, TJ's Fenix 8: every symbol in the notes check drew, the two emoji in colour (`docs/DATA.md`). Characters outside the Basic Multilingual Plane reach the watch. The bold letters themselves are still to be seen with `make live-check-notes`.
- 2026-11-17, TJ's photos: the note's lines are one size, and a note has no markup.

## Alternatives rejected

- Hevy's name in the step, in place of Garmin's: Garmin drops it (2026-11-10).
- No Garmin exercise at all, so the watch shows something generic: the watch would show only a category such as "Lunge", and Garmin Connect and Strava would lose the exercise.
- A smaller font: a note has none to set.
- The name in plain letters: safe on any font, but TJ chose to try bold. If the watch doesn't draw the bold letters, the plain name is the fallback.

## Consequences

`tests/test_workout.py` pins the first line and the bold mapping, and `make live-check-notes` puts one of each note on the watch. Garmin Connect's step list shows the same bold letters, and a screen reader may spell them out. Every workout's notes change, so every Garmin workout is rewritten once.
