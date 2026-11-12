# 0015. Every set but a warm-up lists last time's working sets in its note, from the last workout of any kind that logged the exercise

- Status: Accepted
- Date: 2026-11-11
- Decider: TJ, on #3: the note's form (option A), which session counts, both kinds of workout, and the switch.
- Issues and PRs: #3, #47, #55
- Cited in code as: #3
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-30b, C-12, S-2, F-20a, F-12 and F-4 in [`docs/SPEC.md`](../SPEC.md)

## Context

Hevy shows beside each set what was lifted last time, and the watch showed only the target. A Garmin step carries one note, the note shows on the set's own screen, and every set of an exercise must carry the same note for matching sets to share a repeat group (F-20a). Hevy's "Previous Workout Values" setting picks between the last workout of any kind and the last one of the same routine, and says it does not apply to Hevy Trainer workouts.

## Decision

`previous.py` keeps, in memory, for each exercise template id, the working sets (every set but a warm-up) of the newest logged workout that holds the exercise and a working set of it, with that workout's id and start. The first ask for an exercise reads `GET /v1/exercise_history/{id}` for the last 365 days, once, and keeps the answer, an empty one too. The public API only, so a user without `HEVY_SESSION` gets it. When Hevy refuses one exercise's history with a 4xx, that exercise is kept as having none and the log says so once at WARNING: a refusal is not fixed by asking again, and without this the read would fail every poll and no routine would sync.

The workout events keep it current. An updated workout replaces an exercise's sets when it is the kept workout or starts no earlier than it. When the kept workout no longer holds a working set of the exercise, the entry goes, and the next ask reads the history again. A deleted workout drops every entry kept from it. An exercise not yet asked for is left to its first history read. `app.py` reads the events once a poll, before the routines, for this and for Hevy Trainer alike, and only when one of them is on. The cursor lives in memory, starts at startup and moves only once Hevy has answered; a failed read is waited out by Hevy's backoff. Trainer is told with `Trainer.logged`, which holds until Trainer next reads its inputs, so its own backoff does not lose it.

`workout.py` appends the block to the set's note on its own line, or makes it the whole note. The note's own parts moved to lines of their own with it (TJ, 2026-11-11): the set type, then the rep range or distance as `Goal: 4-6 reps`. On one line, `Drop set: 4-6 reps` is 18 characters, which the watch wraps, leaving `reps` alone above the block.

```
Goal: 4-6 reps
Previous (lb):
65 x 6 @ 7
65 x 6 @ 7.5
65 x 5 @ 8
```

The heading names the unit the weights go to Garmin in (F-21a), and is `Previous:` when no listed set has a weight. It was `Prev (lb):` in the watch check; TJ chose the whole word on 2026-11-11, Hevy's own name for the column. `Previous sets (lb):` is 19 characters, and the watch wrapped a line of 18. `Previous (lb):` is 14, and has not been on the watch. A line is the weight, rounded to one decimal, `x` and the reps, the time (`1m 30s`) or the distance (`25 m`, `27 yd`), then ` @ ` and the RPE when the set has one. A line of more than 8 digits drops the space after `x` and after `@`. A set logged with neither a weight nor an amount is left out. Warm-up sets keep their note as it was. `ENABLE_PREVIOUS_VALUES=false` reads no history and leaves every note as before.

## Evidence

- 2026-11-11, three runs of `make live-check-notes` on TJ's Fenix 8 (#47): a set's note shows on its own screen, a line break starts a new line, one line holds 14 digits, a wider line wraps at a space, the screen shows about six lines and scrolls through a longer note, and Garmin stored a 110-character note whole. `102.5 x 12 @ 9.5` fit on one line, `1002.5 x 12 @ 9.5` did not, and `1002.5 x12 @9.5` did.
- 2026-11-11, read in the Hevy app: Workout Settings has "Previous Workout Values", "Any workout" by default and "Same Routine" as the other choice, with "This configuration will not be applied to Hevy Trainer workouts."
- 2026-11-11, the recorded shapes (`tests/data/recorded_shapes.json`): an exercise history row names `workout_id`, `workout_start_time`, `set_type`, `weight_kg`, `reps`, `rpe`, `duration_seconds` and `distance_meters`; an updated event holds the whole workout, its sets naming the same fields but the type `type`.

## Alternatives rejected

- **The unit and the word RPE on every line** (#3, option B), as in `65 lb x 6 @ RPE 7.5`: the watch broke that line in two.
- **Each set's own previous numbers on that set** (#3, option C), as Hevy shows them: sets with different notes can't share a repeat group, so the watch's SET 1/3 counter falls back to SET 1/1, and it needs Hevy's rule for matching one set to another.
- **Follow Hevy's "Same Routine" setting**: the setting is not in the public API, and Hevy says it does not apply to Trainer workouts.
- **Read the history on every poll**: one call per exercise per poll, where the events already say when anything changed.
- **A second events cursor for this module**: two reads a poll of the same feed, and two cursors to keep right.

## Consequences

`tests/test_previous.py`, `tests/test_workout.py` (`PreviousTest`), `tests/test_routines.py`, `tests/test_trainer.py` and `tests/test_app.py` (`PreviousTest`, and the events tests in `TrainerTest`) hold it. A note that didn't change leaves the version hash (F-12) alone, so a quiet poll makes no Garmin call (F-4a). It costs one history read per exercise at startup, and for a user without Hevy Trainer one events read a poll. Each saved workout rewrites and sends again every synced workout that shares an exercise with it. The watch can show other numbers than the Hevy app for an exercise in two routines when Hevy is set to "Same Routine". A set with a four-digit weight with a decimal, three-digit reps and an RPE with a decimal may still wrap.
