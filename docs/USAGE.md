# Usage

What you see when it runs, and what to do when it breaks.

## In Garmin Connect and on the watch

- One strength workout per Hevy routine: `Hevy: {routine}` for a routine in no folder, `Hevy/{folder}: {routine}` for one in a folder.
- With Hevy Trainer on, one per Trainer workout: `Hevy/Trainer: Upper (C2-W2)`, with the cycle and week the Hevy app shows.
- Each has a four-line description that marks it as the app's. Don't edit it: without it the app no longer knows the workout and makes a new one.
- Every routine is on today's calendar, so the watch offers them when you start a strength activity. Of the Trainer workouts, only the one Hevy says is next is on the calendar. When that changes in Hevy, because you logged one or reordered them, the calendar follows within a minute. The others stay in the watch's saved workouts.
- With many workouts on today, the watch's prompt lists them all under "Dismiss" (eight, on 2026-11-10). Dismiss it and it comes back the next time you start a strength activity. Once you've done one of today's workouts, the prompt stops offering that one and keeps the others; it is still in the saved list. One evening the next Trainer workout was missing from the prompt as well, after another workout had been recorded that day (spec U-10); it was still in the saved list.
- A change in Hevy reaches Garmin Connect within a minute, and the watch at its next sync with your phone.
- Every set has a note, one page down from the main screen during the set. It shows what the watch's set-info screen shows, which is otherwise buried in the step list, under Hevy's name for the set type:

  ```
  Warm Up Set
  4-6 Reps
  35 lbs
  Hevy: Seal Row (Dumbbell)
  ```

  The type is `Warm Up Set`, `Normal Set`, `Failure Set` or `Drop Set`. The target is the reps, a time such as `0:30`, or a distance such as `22 yd`. A weight is whole unless Hevy has a fraction (`17.5 lbs`), and an assisted exercise's weight reads `Assisted 20 lbs`. The last line is Hevy's name for the exercise, only when Garmin's name has a word Hevy's doesn't: `Arnold Press` for Hevy's `Arnold Press (Dumbbell)` gets none.
- A warm-up gets the same rep range as the sets after it, as the Hevy app shows it. Like every set with reps, it waits for the Lap press.
- An exercise swapped in a Trainer workout reaches Garmin only when you answer "Replace permanently?" with Yes. A swap for that workout only (No) stays on your phone, and the watch keeps the old exercise ([issue 44](https://github.com/zimmertr/hevy-garmin-sync/issues/44)). To do the new exercise from the watch, answer Yes, and swap back after the session. Routines work the same way: only an edit to the routine itself reaches Garmin, not an exercise replaced in a workout you've started from it.
- A unit set for one exercise in Hevy reaches Garmin at midnight, or after you save, edit or delete a workout, not within a minute. Press Sync now to send it at once.
- A routine deleted in Hevy leaves Garmin Connect and the calendar. The copy in the watch's saved workout list stays until you delete it on the watch.

## On the status page

Open `http://localhost:8080` under Compose, or the Service's address under Kubernetes (`kubectl port-forward svc/hevy-garmin-sync 8080` if it has none outside the cluster). TJ's is at http://atlas.sol.milkyway. The page has no sign-in: anyone who can reach the port sees your workouts and can press its buttons.

- **Sync now** reads Hevy and syncs all workouts to Garmin Connect. It writes what changed, tries again any workout Garmin refused, sends every workout to the watch again, and reads Hevy Trainer's preferences and logged workouts again. A hand edit in Garmin Connect stays.
- **Force sync** reads Hevy and overwrites all workouts on Garmin Connect, which undoes any hand edit there. Each workout keeps its place on the calendar. It also reads last time's sets for the status page from Hevy again.
- From a terminal, the same with `sync` and `sync --force`: `docker compose exec hevy-garmin-sync python3 -m hevy_garmin_sync sync`, or `kubectl exec deploy/hevy-garmin-sync -- python3 -m hevy_garmin_sync sync`.
- One sync a minute. Within a minute of the last one, the page and `sync` say how many seconds are left. A press while a sync runs joins it. While Garmin is making the app wait, the sync runs when the wait ends, and the page says so.
- A sync costs about 3 Garmin calls per workout, and Garmin is known to block accounts that call too often. Use it when something looks wrong, not on a timer.
- Services: Hevy, Hevy Trainer and Garmin, each working, waiting with the reason and the next try, or sign-in rejected with the fix. The tab's title and icon turn yellow while one waits, and red while one is rejected or Garmin refuses a workout.
- Workouts: each one's schedule, when it last synced, links to Hevy and Garmin Connect, and Garmin's reason if it refused it. Its exercises show the Garmin exercise each got, the sets, the rest and the weight. One matched by muscle group and equipment has "Report this match", which opens an issue with both exercises filled in.
- The log: the last 5,000 lines, 200 at a time, with a switch for errors and warnings only.
- Settings: every variable, with the secrets shown only as set or unset.

## In the log

| Line | Means |
|---|---|
| `Sync: created 2, updated 0, deleted 0, scheduled 2, unscheduled 0, failed 0` | One per full run, and one per poll that changed something |
| `Nothing changed in the last hour (60 polls)` | The app is alive and Hevy didn't change |
| `Hevy routine folder: id 42, title 'Push Pull Legs'` | At startup, every folder, for `INCLUDE_HEVY_FOLDERS` |
| `Custom Hevy exercise 'My Cable Raise' (muscle group shoulders, equipment machine) is Garmin's SHOULDER_PRESS / SMITH_MACHINE_OVERHEAD_PRESS, by muscle group and equipment` | The Garmin exercise one of your own Hevy exercises got, logged the first time it syncs and when that changes. Ends `from CUSTOM_EXERCISE_MAP` when the variable chose it |
| `Hevy Trainer: Side Bend (Dumbbell): 40 lbs (up)` | A Trainer prescription, logged when it is first worked out and when it changes |
| `Hevy Trainer: ...: no prescription (...)` | Trainer gives that exercise no weight, and why |
| `Manual sync asked for (forced: every workout is rewritten)` | Sync now, Force sync or `sync` started a run. A plain one ends at `asked for` |
| `Trying '<workout>' again, which Garmin refused` | Another try at a workout Garmin refused earlier. If Garmin refuses it again, an ERROR line follows |

## When it breaks

| You see | Do |
|---|---|
| It exits at startup naming a variable | Fix that variable. The message says how |
| The status page shows a sign-in rejected, or the pod isn't ready (`0/1`) | A sign-in was rejected. The app keeps running and leaves that service alone; the page and the log say which one, and the rows below say what to do. Set the new value, then restart the app |
| `login` says `Sign-in failed` and names a cloud server | Garmin blocks sign-ins from a lot of cloud IPs. Run `login` at home, even if the app runs in the cloud, and set `GARMIN_TOKEN` there |
| `Garmin rejected the app's credentials` | Nothing reaches Garmin until it is fixed. Run `login` again and set `GARMIN_TOKEN` to the new value |
| `Hevy rejected the app's credentials; check HEVY_API_KEY` | Nothing is read from Hevy until it is fixed. Make a new key at https://hevy.com/settings?developer. The key needs Hevy Pro |
| `Hevy Trainer rejected the app's credentials` | Copy the `auth2.0-token` cookie from hevy.com again, in a private window you then close without logging out, and set `HEVY_SESSION` to it. Routines keep syncing meanwhile, and the Trainer workouts stay in Garmin as they were |
| `... can't be reached or is failing ... Trying again in N min` | Nothing. It retries by itself, waiting longer each time, up to 30 minutes |
| `... is rate limiting the app and said how long to wait` | Nothing. It waits as long as Hevy or Garmin asked, even past 30 minutes. The line says how long |
| `Garmin is rate limiting the app` | Nothing. It waits at least 15 minutes |
| `Garmin refused '<workout>' (N steps): ... It is tried again at 17:45` | Garmin won't take that one workout. The others still sync. It is tried again 5 minutes later, then at gaps that double until midnight, then once a day at midnight; the line says when. A change to the routine is tried at once, and so is a restart. Open an issue with the line |
| `No exercise map row for Hevy exercise ...` | A built-in Hevy exercise the map doesn't know. It still syncs, under the closest exercise by muscle group. Open an issue so it gets a proper row |
| `Hevy's program names no next workout` | Hevy didn't say which Trainer workout is next. Until it does, every Trainer workout not logged this week is on today. Open an issue with the line |
| `'<folder>' in INCLUDE_HEVY_FOLDERS is gone` | The folder was renamed or deleted in Hevy. Its workouts are kept. Fix the variable and restart |
| A workout shows the wrong exercise name on the watch | For a built-in Hevy exercise, the map has a poor row for it. Open an issue or a PR against `src/hevy_garmin_sync/data/exercise_map.csv`. For one of your own, find its `Custom Hevy exercise` line and set `CUSTOM_EXERCISE_MAP` ([CONFIGURATION.md](CONFIGURATION.md)). The workout is rewritten and sent to the watch again |
| `CUSTOM_EXERCISE_MAP names CURL/CURLS, which Garmin doesn't have` | It exits at startup. Pick a category and an exercise from [`garmin_exercises.json`](../src/hevy_garmin_sync/data/garmin_exercises.json), in capitals as written there |
| `CUSTOM_EXERCISE_MAP entry '...' is not title-or-id=CATEGORY/NAME` | It exits at startup. Write the entry as `My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE`. A title with a comma in it goes by its exercise template id |
| `CUSTOM_EXERCISE_MAP names '...', a built-in Hevy exercise, and is ignored for it` | The variable is for your own exercises only. Remove the entry; if the built-in's Garmin exercise is wrong, open an issue |
| `sync` says `The app isn't running here: nothing answers on port 8080.` | Run it inside the app's container, as above. If the app runs, `HTTP_PORT` names another port there |
| Two copies of a workout in the watch's saved list | An old copy from before a delete. Remove it on the watch |
