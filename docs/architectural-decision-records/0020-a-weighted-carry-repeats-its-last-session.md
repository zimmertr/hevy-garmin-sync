# 0020. A Hevy Trainer exercise logged by weight and distance or time repeats its last session

- Status: Accepted
- Date: 2026-11-17
- Decider: TJ, after a leg day, who chose to reverse the decision of 2026-11-10
- Issues and PRs: #101
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-46a in [`docs/SPEC.md`](../SPEC.md)

## Context

On 2026-11-10 TJ confirmed that Walking Lunge (Dumbbell), a `short_distance_weight` exercise, gets no weight, and that the app doesn't fill in the last logged one as hevy-trainer-sync did. During the Lower of 2026-11-17 the watch asked for 12 reps, the program's rep range, and its weight screen showed 0 lbs. The Hevy app showed 25 lbs and 25 yd.

## Decision

An exercise logged by weight and distance (`short_distance_weight`) or by weight and time (`weight_duration`) repeats its last session in its template, set by set, with no rep range. A set past last session's count repeats its last. With no last session, or no working set in it, it gets nothing.

## Evidence

- 2026-11-17, TJ's screenshot of the Hevy app: Walking Lunge's three sets showed 25 lbs and 25 yd in white, the same as Romanian Deadlift's prescribed 130 lbs, with the previous column at 25lbs - 25yd.
- 2026-11-17, TJ's watch: `Next: Walking Dumbbell Lunge 12 Reps`, and 0 lbs on the weight screen after the set.

## Alternatives rejected

- No weight (the decision of 2026-11-10): the Hevy app does fill the numbers in, and the watch asked for reps the lifter doesn't count.
- 25 reps for 25 yd: only true for a lifter who counts a yard as a lunge.
- Only `short_distance_weight`: TJ took weight and time along, since Trainer skipped both for the same reason. It is not checked against the app yet.

## Consequences

`tests/test_trainer.py` and `tests/test_trainer_rules.py` pin it. A deload week repeats the last session as it is, which is unchecked against the app.
