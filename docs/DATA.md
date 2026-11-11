# Data

Each upstream service, its terms, and every quirk found, dated. The spec's [section 10](SPEC.md#10-known-api-facts-verified-unless-marked) and its watch tests (F-21a, F-20a, F-27, F-30, F-31a) hold the facts verified before the build. A finding made while building or running the app goes here, dated, in the same PR as the code that relies on it. A finding first recorded in hevy-trainer-sync, the archived tool this app replaced, keeps the date it was recorded there.

## Hevy

- **Public API** (`https://api.hevyapp.com/v1`, header `api-key`): routines, routine folders, exercise templates, workout events and exercise history. Needs a Hevy Pro API key from Hevy's settings. Documented at https://api.hevyapp.com/docs. The app only reads.
- **Private API**, Hevy Trainer only (`https://api.hevyapp.com`): the API the Hevy app and web use, undocumented, signed in with the `auth2.0-token` cookie from hevy.com. Hevy can change it without notice. Hevy's terms allow suspending accounts for unauthorized use, and the README says so. The app only reads, apart from refreshing its own session.

### What the app calls

| Call | When |
|---|---|
| `GET /v1/routine_folders`, `GET /v1/routines` | Every poll. Ten per page, so a call per ten routines |
| `GET /v1/exercise_templates` | Once, on first use, a hundred per page. A template made later is read by itself |
| `GET /v1/workouts/events` | Every poll, with Trainer on |
| `GET /v1/exercise_history/{id}` | Only for a Trainer exercise new to its workout, once per exercise until the logged workouts are next read |
| `GET /hevy_trainer/v3/program` | Every poll, with Trainer on |
| `GET /v2/user_preferences`, `GET /hevy_trainer/user_preferences`, `GET /exercise_template_units`, `GET /user_workouts_paged` | At startup, at local midnight and after a workout event, with Trainer on |
| `POST /auth/refresh_token` | When the session has expired, about every 30 minutes |

Every call has a 30 second timeout (O-1a) and a `User-Agent` that names the app and its repo.

### Findings

- **Hevy publishes no rate limit** for the public API. Its docs ask that a job running hourly or daily not send its requests at minute :00. The app polls every minute, which that request does not speak to (read 2026-11-05, first recorded in hevy-trainer-sync).
- **Hevy has one webhook, for saved workouts.** It is set up in the "Webhooks" section of the developer settings page (https://hevy.com/settings?developer): "Subscribe to our webhook and get notified when you save a new workout." Hevy sends a POST with `{"workoutId": "<id>"}` to a URL the user gives, with an authorization header the user gives, and expects a 200 within 5 seconds. The section says nothing about routines. Hevy's published API spec has no webhook path (14 paths), so the page is the only place to set it up (2026-11-10). The app has no receiver: routines have no feed, and a receiver needs a listening port, which spec F-2 rules out.
- **Routine page size** is at most 10; exercise templates take 100 (Hevy's OpenAPI spec, 2026-11-10).
- **A routine's superset field** is `superset_id`, and a set has no RPE field (OpenAPI spec, 2026-11-10).
- **Hevy's exercise list** held 451 built-in exercises on 2026-11-10. The map's ids and titles were checked against it that day: one row was missing (a second `Sled Push` id) and three had no title. Four rows are ids Hevy no longer lists; they stay, since a row nothing asks for costs nothing.
- **An exercise template's `type`** came back as `bodyweight_weighted` and `bodyweight_assisted` on 2026-11-10, where the API reference lists `bodyweight_reps` and `bodyweight_assisted_reps`. That read went through a connector, not the raw API, so the app takes both spellings.
- **A template's `equipment`** matched Hevy Trainer's own equipment value for all 447 exercises compared (2026-11-10, spec F-40).
- **A routine's weights** are kilograms with the full conversion (`22.67964547178199` for 50 lbs), and a set with a rep range carries `rep_range` with `start` and `end` (2026-11-10).
- **`GET /v1/workouts/events`** lists `updated` and `deleted` events, each with the whole workout, newest first (2026-11-05, first recorded in hevy-trainer-sync).
- **The session's refresh token rotates** on every refresh, and the refresh needs the old access token in `Authorization` even when it has expired (2026-11-04). The app saves the new pair before it makes another call.
- **Not yet known:** whether the session's refresh token has an absolute lifetime. The question was first recorded in hevy-trainer-sync on 2026-11-04 and is still open.
- **`/user_workouts_paged`** answered a `limit` of 10 with a 400 on 2026-11-07. The app asks for 3.
- **The program's `current_week`** is not the week the Hevy app shows ([HEVY_TRAINER_RULES.md](HEVY_TRAINER_RULES.md)).
- **The program also carries** `next_workout_index`, `program_variety`, `exercises_rotated_at` and `edits` (2026-11-04, first recorded in hevy-trainer-sync). The app reads `next_workout_index` (below) and none of the other three.
- **`exercises_rotated_at`** read Thursday 29 October 2026, so exercises do not rotate on a week boundary (2026-11-04, first recorded in hevy-trainer-sync).
- **Not yet seen live:** what the program call answers for an account with no program (the app takes a 404 or a reply without a program as "no program"), and a row of `/exercise_template_units`. That call answered with an empty list on 2026-11-10, for an account that logs no exercise in the other unit; the app logs the shape, without values, the first time.
- **A Trainer template's `name`** held its key (`upper_2x_a`) on 2026-11-10, not a display name. The app reads a name in a key's form as a key, so the workout is called "Upper".
- **The first run against a real account** (2026-11-10, from a clone, Hevy Trainer on): two routines and a two-workout program became four Garmin workouts with no failure.
- **The program's `next_workout_index`** is the workout the Hevy app would start next, counted in the templates' `index` order. hevy-trainer-sync put that one workout on today from 2026-11-04 to 2026-11-10, and this app does the same since #25 (spec F-33). Not yet seen live, as of 2026-11-10: how it moves after a logged session, after a reorder in the Hevy app, and across a week change. A value that is missing, not an integer or out of range is logged as a WARNING, and the app falls back to keeping the week's logged workouts off the calendar.

## Garmin Connect

Garmin's unofficial web API, through [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) (MIT). Garmin's official APIs don't fit: the personal API key is read-only, and the Training API needs business access (spec section 1). Garmin may block sign-ins from cloud IPs and accounts that call too often, so the app calls Garmin only when something changed (F-4a) and leaves a second between writes (O-1b).

### What the app calls

| Call | When |
|---|---|
| The user profile | At startup and every full run: pounds or kilograms |
| The workout list, 100 per page | Every full run (startup, local midnight, after a Garmin failure) |
| Create, update or delete a workout | When a routine or Trainer workout was added, changed or removed |
| Send to Device, three calls | After each create and update |
| The calendar, 31 days back through today | Every full run |
| Schedule or unschedule a workout | Every full run, when a workout is created or deleted, and when Hevy Trainer's next workout changes |

### Findings

- **python-garminconnect 0.3.20** times out API calls after 15 seconds and token calls after 30, and retries are turned off: the app has its own waits (O-1).
- **The library rewrites the token file itself** each time Garmin rotates the token. The app writes it again with a flush to disk after each call.
- **Weights go in the user's own unit.** A weight sent in kilograms to a pounds account showed as 0.0 lbs on a Fenix 8 (2026-11-07, spec F-21a). With Garmin Connect set to metric the app sent 20 and 22.5 kilograms. The watch, still set to pounds, showed 44.1 and 49.6 lbs, and 20 and 22.5 kg once the watch itself was set to kilograms (2026-11-10, [#5](https://github.com/zimmertr/hevy-garmin-sync/issues/5)). So the unit to send is Garmin Connect's, and the watch's weight unit is a separate setting on the watch.
- **Garmin takes every exercise category the tables use** in a strength workout: one workout holding all 42 was accepted (2026-11-10). For `BATTLE_ROPE` and `HYPEREXTENSION` the exercise Garmin stored differed from the one sent. What it stored is not known yet.
- **The settings reply has a `timeZone` field** (`America/Los_Angeles` style), and the workout list carries each workout's `description` (2026-11-10).
- **A workout updated in place and sent again** is one copy on the watch, with the new name and weights (2026-11-10, spec U-24).
- **A workout deleted in Garmin Connect stays in the watch's saved list** until it is removed on the watch (2026-11-10, spec F-14).
- **Garmin's exercise list** is published at https://connect.garmin.com/web-data/exercises/Exercises.json: 47 categories and 1,536 exercises on 2026-11-10. `tests/data/garmin_exercises.json` holds its keys.

## Strava

The app never calls Strava (spec S-1). Garmin's own Strava connection forwards the watch's recording, so the planned workout on the watch decides what Strava shows (spec G-2). These findings are why.

### Findings

- **Garmin forwards a new activity to Strava** within seconds of the phone sync, and nothing after that. A later change to the activity in Garmin Connect does not reach Strava (2026-11-05, first recorded in hevy-trainer-sync).
- **Strava shows what Garmin first forwarded.** Its API cannot edit an activity's sets or delete an activity, and has had no delete since 17 January 2017 (2026-11-05, first recorded in hevy-trainer-sync).
- **Without a planned workout the watch guesses the exercise** for each set, so the name can change from set to set within one exercise (2026-11-05, first recorded in hevy-trainer-sync).
- **The watch's FIT files store weight in sixteenths of a kilogram.** 25, 45 and 80 lb entered on the watch read 24.9, 45.1 and 80.1 lb on Strava (2026-11-05, first recorded in hevy-trainer-sync).
- **Not yet known:** whether the watch records the planned rep target or its own rep count for a set that is not edited on the watch. The question was first recorded in hevy-trainer-sync on 2026-11-05 and is still open.

## Quirks

- **kustomize 5.8 adds no namespace to a chart's resources.** Argo CD 3.5.7 runs kustomize 5.8.1, and on 2026-11-10 it refused chart 0.2.0 with "Namespace for hevy-garmin-sync apps/v1, Kind=Deployment is missing", while kustomize 5.7.1 rendered the same folder with the namespace set. The chart's templates now state `.Release.Namespace` themselves, and the `Chart` job checks it.
