# 0009. Only the Hevy Trainer workout Hevy says is next is on today, and the calendar follows it within a poll

- Status: Accepted
- Date: 2026-11-10
- Decider: TJ, 2026-11-10, on #25: put only the next Hevy Trainer workout on today, "as long as rearranging them in Hevy gets synced to Garmin Connect promptly".
- Issues and PRs: #25
- Cited in code as: #25, in `src/hevy_garmin_sync/trainer.py` and `src/hevy_garmin_sync/sync.py`
- Guide: [`docs/SPEC.md`](../SPEC.md), F-31 and F-33

## Context

The app put every Hevy Trainer workout not logged this week on today's calendar (F-33), so on a program of three or more days the watch offered two or more and TJ picked the right one himself. Hevy's program reply names the next workout in `next_workout_index`, and hevy-trainer-sync, the tool this app replaced, followed it. The calendar also moved only at a full run (startup, midnight, after a failure), so a workout logged at 10:00 kept its entry until midnight.

## Decision

- `Trainer.plans` reads `next_workout_index` against the templates sorted by `index`, and puts every other template in `off_calendar`. A missing, non-integer or out-of-range value falls back to the logged-this-week rule (F-33) and logs one WARNING until Hevy names a next workout again.
- Between full runs, `Sync.run` compares each listed workout's wanted place (on or off today) with what it knows it put on today, and acts only on the difference. A workout that left the calendar is unscheduled by the entry id in `_entries`; one that joined is scheduled for today. It reads no calendar on a poll (F-4a), so an entry whose id Garmin did not give stays until the next full run.
- Routines are unchanged: all on today. Every Trainer workout stays a Garmin workout and stays in the watch's saved list.

## Evidence

- 2026-11-10, read in both codebases: `Trainer.plans` never read `next_workout_index`; hevy-trainer-sync read it and kept one calendar entry, the next workout, on today. It relied on it from 2026-11-04 to 2026-11-10.
- No dated measurement of how Hevy moves `next_workout_index` after a logged session, a reorder in the Hevy app, or a week change. `docs/DATA.md` lists it as not yet seen live.

## Alternatives rejected

- Follow `next_workout_index` but move the calendar only at midnight: no new Garmin calls, but it fails TJ's condition.
- Keep F-33's rule (every workout not logged this week on today): the watch keeps offering workouts Hevy would not start.

## Consequences

- One Hevy Trainer workout is always on today. F-33's rule showed none once the week's workouts were all logged.
- Each change of the next workout costs two Garmin writes, a second apart (O-1b). A poll where it did not change makes none. `tests/test_sync.py` (`MoveTest`) and `tests/test_trainer.py` (`CalendarTest`, `NoNextWorkoutTest`) hold this in place.
- If the field ever points at the wrong workout, the watch offers the wrong one. The others stay in the watch's saved workouts.
