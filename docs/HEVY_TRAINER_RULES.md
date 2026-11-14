# Hevy Trainer rules

Hevy's servers send a Trainer program without weights, warm-up weights or a week number. The Hevy app works those out on the phone. This page writes down the rules this app follows to get the same answers, so the watch shows what the Hevy app shows. `src/hevy_garmin_sync/trainer_rules.py` is the code, and spec section 6 (F-40 to F-48) is the requirement.

The rules match Hevy app 3.2.5, and no release through 3.2.7 changed them. Every new release is checked outside this repo, and a changed rule comes back as an issue (F-48, record 0018). A difference between the watch and the app is still worth an issue.

## What is read

| From | Call | For |
|---|---|---|
| Hevy's private API | `GET /hevy_trainer/v3/program` | The program: its `created_at`, `deloads_enabled`, `next_workout_index`, and each template's exercises with `set_count`, `warmup_set_count`, `rep_range` and `rest_seconds`. `next_workout_index` is the workout the Hevy app would start next, counted in the templates' `index` order; only that one goes on today's calendar |
| Hevy's private API | `GET /v2/user_preferences` | `username`, `weight_unit`, `first_weekday` |
| Hevy's private API | `GET /hevy_trainer/user_preferences` | `availableWeights`: the dumbbells, bars and plates the user owns |
| Hevy's private API | `GET /exercise_template_units` | The exercises the user logs in the other unit: a row per exercise, with `exercise_template_id` and `weight_unit` |
| Hevy's private API | `GET /user_workouts_paged` | Logged workouts since the program began, each with its `trainer_workout_template_id` |
| Hevy's public API | `GET /v1/exercise_templates` | Each exercise's `type` and `equipment`. The equipment matched Hevy Trainer's own value for all 447 exercises compared on 2026-11-10 |
| Hevy's public API | `GET /v1/exercise_history/{id}` | The last twelve months of one exercise, only for an exercise new to its workout |
| Hevy's public API | `GET /v1/workouts/events` | Whether a workout was saved, edited or deleted since the last poll |

The program and the events are read on every poll. Everything else is read at startup, at local midnight, and after a workout event.

An exercise swapped in the Hevy app and answered "Replace permanently? Yes" is already in its template's `exercises` the next time the program is read, so it reaches the watch like any other change. A swap answered "No", for that workout only, is kept on the phone until the workout is saved and is in nothing read here, so the watch keeps the old exercise (2026-11-11). Tracked in [issue 44](https://github.com/zimmertr/hevy-garmin-sync/issues/44).

## The week

- A week starts on the user's first weekday (`first_weekday`) at local midnight.
- The program week is the number of whole weeks from the week the program was created in to the current week, plus one.
- A cycle is 6 weeks, or 7 when the program has deloads on. Cycle = floor((week - 1) / n) + 1. Week of the cycle = (week - 1) mod n + 1.
- The seventh week of a 7-week cycle is the deload week.
- The program's own `current_week` field is not the week the app shows.

## Which exercises get what

- An exercise the program marks as resistance work, with a rep range, is the only kind that gets anything.
- Logged by weight and reps (`weight_reps`), or weighted bodyweight (`bodyweight_weighted`, also spelled `bodyweight_reps`), on a machine, dumbbell or barbell: a weight.
- Logged by reps alone (`reps_only`): a rep range.
- Anything else (time, distance, kettlebells, bands, plates, other equipment): nothing. The workout carries the program's rep range and no weight, and the log says why.

## History

An exercise's history is the logged workouts that came from the same Trainer template and hold the exercise, oldest first. Workouts logged in a deload week are left out. A workout with no start time is left out. The newest one is the previous session.

Only sets of type `normal` count as working sets. A missing rep count or weight counts as zero.

## The next weight

1. The base is the lightest working set of the previous session.
2. Fewer working sets than the program's set count: no change.
3. Every working set at or above the top of the rep range: base × 1.05.
4. Every working set below the bottom of the rep range: base × 0.95.
5. Anything else: no change.
6. The result is rounded to a weight the user can load (below), in the exercise's unit.
7. In a deload week the result is then multiplied by 0.6 and rounded to the nearest loadable weight.

Weights change only after a logged session, never just because the week turned. The deload multiplier is the exception: it follows the week.

The unit is the account's `weight_unit`, unless the user logs that exercise in the other unit. One kilogram is 2.20462 lb, and a weight in its unit is rounded to two decimals before it is matched to equipment.

## Rounding to equipment

| Equipment | Weights the user can load |
|---|---|
| Machine | Steps of 2.5 kg or 5 lb |
| Dumbbell | Each dumbbell the user owns, doubled: a dumbbell exercise is logged as both dumbbells together |
| Barbell | Any bar the user owns plus the same plates on both sides, any number of each plate |

Where the user's preferences list nothing, these stand in:

| | Kilograms | Pounds |
|---|---|---|
| Plates | 25, 20, 15, 10, 5, 2.5, 1.25 | 45, 25, 10, 5, 2.5 |
| Bars | 20 | 45 |
| Dumbbells | 2.5 to 30 in steps of 2.5, then 35, 40, 45, 50 | 5 to 80 in steps of 5, then 90, 100 |

How a target becomes a loadable weight depends on the direction:

- **No change:** the previous weight, as it was. On a machine, the step nearest to it.
- **Up, machine:** the next step at or above the target.
- **Down, machine:** the next step at or below the target.
- **Up, dumbbell or barbell:** the target if it can be loaded. If not, the heaviest loadable weight between the previous weight and the target. If there is none, the first loadable weight above the target.
- **Down, dumbbell or barbell:** the target if it can be loaded. If not, the lightest loadable weight between the target and the previous weight. If there is none, the heaviest loadable weight below the target.
- **No direction** (warm-ups, the deload weight, a new exercise): the nearest loadable weight. Of two equally near, the lighter. On a machine, half a step rounds up.

A weight nothing can load gives no prescription.

## Warm-ups

- One warm-up set: 60% of the working weight.
- Two or more warm-up sets: 40%, then 60%. A third or later warm-up gets no weight.
- Each is rounded to the nearest loadable weight.
- A warm-up gets the working sets' rep range, as the Hevy app shows it on the warm-up rows.

## The next rep range

For an exercise logged by reps alone, the rep range moves along this ladder:

`4-6`, `6-8`, `8-12`, `12-15`, `15-20`, `20-25`, `25-30`

- It starts at the program's rep range.
- Each past session, oldest first, moves it by the same rule as the weight: every working set at or above the top moves it up a rung, every working set below the bottom moves it down a rung, anything else leaves it.
- Up is the first rung that starts at or above the current top. Down is the highest rung that starts below the current bottom. At either end of the ladder it stays.
- In a deload week it is one rung down from where it stands.

## A new exercise

An exercise with no previous session in its template (after a rotation, say) starts from the user's best estimated one-rep max for that exercise.

- Only exercises logged by weight and reps get a starting weight.
- A set's estimated one-rep max is its weight divided by the factor for its reps:

| Reps | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Factor | 1 | 0.97 | 0.94 | 0.92 | 0.89 | 0.86 | 0.83 | 0.81 | 0.78 | 0.75 |

| Reps | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|
| Factor | 0.73 | 0.71 | 0.7 | 0.68 | 0.67 | 0.65 | 0.64 | 0.63 | 0.61 | 0.6 |

| Reps | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 |
|---|---|---|---|---|---|---|---|---|---|---|
| Factor | 0.59 | 0.58 | 0.57 | 0.56 | 0.55 | 0.54 | 0.53 | 0.52 | 0.51 | 0.5 |

- Past 30 reps the factor is 0.5. A set of zero reps gives nothing. Warm-up sets are left out.
- The best estimate of the last 3 months is used. With none, the best of the last 12 months. With none, no weight.
- The starting weight is that one-rep max times a share for the program's rep range. The first row the range fits inside wins:

| Rep range fits inside | Share |
|---|---|
| 4 to 6 | 0.80 |
| 10 to 12 | 0.64 |
| 8 to 12 | 0.67 |
| 12 to 15 | 0.63 |
| anything else | no weight |

- The result is rounded to the nearest loadable weight, and warm-ups follow from it.

## Checked against the Hevy app

| Date | Case | The app showed | This app gives |
|---|---|---|---|
| 2026-11-04, 2026-11-06 | A program created on a Monday, read in its eighth calendar week, no deloads | Cycle 2, week 2 of 6 | C2-W2 |
| 2026-11-06, 2026-11-07 | Side Bend (Dumbbell), last session at 35 lb with every set at the top of its range | 40 lb | 40 lb |
| 2026-11-06, 2026-11-07 | Lying Leg Raise, logged by reps, every set at the top of its range | The next rep range up, 15-20 | The next rung of the ladder |
| 2026-11-06, 2026-11-07 | Goblet Squat, two warm-ups, last session at 80 lb inside its rep range | 80 lb, warm-ups 30 and 50 lb | 80 lb, warm-ups 30 and 50 lb |
| 2026-11-10 | The 14 exercises of both workouts of a two-workout program, as the running app worked them out | 12 weights with their warm-ups, one rep range, and one exercise with no weight | The same on all 14. TJ: "These look correct" (#22) |
| 2026-11-11 | One exercise logged in the other unit, kilograms | 20 kg | 20 kg |
| 2026-11-11 | One exercise swapped in permanently, weighted bodyweight (`bodyweight_weighted`) with no equipment, never logged in its template | No suggested weight, only the last session's numbers as placeholders | No prescription |
| 2026-11-13 | Goblet Squat, two warm-ups, rep range 4-6 | 4-6 on both warm-ups and on the three working sets | 4-6 on all five |

On 2026-11-10 the first run against a real account gave the same weight and warm-ups as hevy-trainer-sync, the tool these rules were first written for, on all 12 weighted exercises of a two-workout program, and the same rep range on the one logged by reps.

Not yet checked against the app: a new exercise's starting weight, a deload week, an account in kilograms, and a barbell exercise.

## Open points

- **The 3 and 12 month windows** are taken as the last 91 and 365 days. The exact day counts are not confirmed.
