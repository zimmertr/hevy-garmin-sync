# 0012. A custom exercise's Garmin exercise is logged, and one variable, CUSTOM_EXERCISE_MAP, can set it

- Status: Accepted
- Date: 2026-11-10
- Decider: TJ, on #24: do all three parts, and the override is one variable (option A).
- Issues and PRs: #24, #39
- Cited in code as: #24
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Exercise names are data"; spec F-53, F-54 and C-11 in [`docs/SPEC.md`](../SPEC.md)

## Context

A custom Hevy exercise got its Garmin exercise from `custom_exercise_map.csv`, by muscle group and equipment, with `CORE` / `CORE` as the catch-all (spec D-11m), and the app logged nothing about it. Spec F-54 allowed no per-user overrides, but a custom exercise's id belongs to one Hevy account, so `exercise_map.csv` can never hold its row. hevy2garmin, the tool this app replaced, kept a per-user mapping table (read 2026-11-10).

## Decision

`ExerciseMap.find` logs one INFO line per custom exercise: its Hevy title, muscle group and equipment, the Garmin pair it got, and whether `CUSTOM_EXERCISE_MAP` or the table chose it. It logs again only when the pick changes.

`CUSTOM_EXERCISE_MAP` holds comma-separated `title-or-id=CATEGORY/NAME` entries. An entry is tried as the exercise template id before the title, as `INCLUDE_HEVY_FOLDERS` does for folders, and a title matches exactly, case included, after trimming spaces. Each entry splits on its last `=`; a title holding a comma goes by its id. It wins over `custom_exercise_map.csv` and applies to custom exercises only.

`config.load` refuses at startup an entry not in that form, the same exercise twice, and a pair not in Garmin's exercise list. To check the pair at runtime, `garmin_exercises.json` moved from `tests/data` (where record 0010 put it) to `src/hevy_garmin_sync/data`, which the image copies whole. The weekly upstream check updates it there.

An entry that names a built-in exercise is ignored with one WARNING when that exercise is seen. It can't be refused at startup: whether a title is built-in is known only once Hevy's templates are read, and a user may give a custom exercise the same title as a built-in one. A wrong built-in is fixed in `exercise_map.csv` for every user (F-54).

The startup log shows the variable as set with its number of entries, never the entries: they are a user's own exercise titles.

## Evidence

- 2026-11-10, read in this app and in hevy2garmin: this app logged nothing for a custom exercise; hevy2garmin kept a per-user table, and for an exercise with no Garmin match set the step's `stepName` to the Hevy title (`buildStep` in `web/lib/garmin-workout.ts`).
- No dated measurement of how a Fenix 8 or Strava shows `stepName`. That is #24's watch check, still to run.

## Alternatives rejected

- **A CSV file in `DATA_DIR`** (#24, option B): the same format as the shipped tables, but editing a file inside a pod's volume is awkward.
- **A variable naming a file to mount** (#24, option C): fits a ConfigMap, but adds one more variable and one more chart template.
- **Refuse an entry naming a built-in at startup**: needs Hevy's template list before the first call, and would refuse a custom exercise that shares a built-in's title.

## Consequences

`tests/test_exercises.py` (`PickTest`), `tests/test_config.py` (`CustomExerciseMapTest`), `tests/test_app.py` and `tests/test_check_upstream.py` hold it. A mistyped pair stops the app at startup, on purpose, so the mistake is seen. A changed entry changes the workout's version hash, so that workout is rewritten and sent to the watch once. A title with a comma in it can only be written by id.
