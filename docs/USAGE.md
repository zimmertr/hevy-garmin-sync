# Usage

What you see when it runs, and what to do when it breaks.

## In Garmin Connect and on the watch

- One strength workout per Hevy routine: `Hevy: {routine}` for a routine in no folder, `Hevy/{folder}: {routine}` for one in a folder.
- With Hevy Trainer on, one per Trainer workout: `Hevy/Trainer: Upper (C2-W2)`, with the cycle and week the Hevy app shows.
- Each has a four-line description that marks it as the app's. Don't edit it: without it the app no longer knows the workout and makes a new one.
- Every routine is on today's calendar, so the watch offers them when you start a strength activity. Of the Trainer workouts, only the one Hevy says is next is on the calendar. When that changes in Hevy, because you logged one or reordered them, the calendar follows within a minute. The others stay in the watch's saved workouts.
- With many workouts on today, the watch's prompt lists them all under "Dismiss" (eight, on 2026-11-10). Dismiss it and it comes back the next time you start a strength activity. The prompt offers the next Trainer workout on a day you haven't trained yet. The one time it was missing was the evening of a day a workout had already been recorded (spec U-10); it is still in the saved list then.
- A change in Hevy reaches Garmin Connect within a minute, and the watch at its next sync with your phone.
- A routine deleted in Hevy leaves Garmin Connect and the calendar. The copy in the watch's saved workout list stays until you delete it on the watch.

## In the log

| Line | Means |
|---|---|
| `Sync: created 2, updated 0, deleted 0, scheduled 2, unscheduled 0, failed 0` | One per full run, and one per poll that changed something |
| `Nothing changed in the last hour (60 polls)` | The app is alive and Hevy didn't change |
| `Hevy routine folder: id 42, title 'Push Pull Legs'` | At startup, every folder, for `INCLUDE_HEVY_FOLDERS` |
| `Custom Hevy exercise 'My Cable Raise' (muscle group shoulders, equipment cable) is Garmin's TOTAL_BODY / TOTAL_BODY, by muscle group and equipment` | The Garmin exercise one of your own Hevy exercises got, logged the first time it syncs and when that changes. Ends `from CUSTOM_EXERCISE_MAP` when the variable chose it |
| `Hevy Trainer: Side Bend (Dumbbell): 40 lbs (up)` | A Trainer prescription, logged when it is first worked out and when it changes |
| `Hevy Trainer: ...: no prescription (...)` | Trainer gives that exercise no weight, and why |
| `Trying '<workout>' again, which Garmin refused` | Another try at a workout Garmin refused earlier. If Garmin refuses it again, an ERROR line follows |

## When it breaks

| You see | Do |
|---|---|
| It exits at startup naming a variable | Fix that variable. The message says how |
| The pod is in `CrashLoopBackOff`, or `docker compose ps` shows it restarting | A sign-in was rejected. The last line of the log says which one, and the rows below say what to do. Nothing syncs until it is fixed; each restart exits again |
| `Garmin rejected the app's credentials` | Run `login` again and set `GARMIN_TOKEN` to the new value |
| `Hevy rejected the app's credentials; check HEVY_API_KEY` | Make a new key at https://hevy.com/settings?developer. The key needs Hevy Pro |
| `Hevy Trainer rejected the app's credentials` | Copy the `auth2.0-token` cookie from hevy.com again, in a private window you then close without logging out, and set `HEVY_SESSION` to it. To sync routines only meanwhile, unset `HEVY_SESSION`, which also takes the Trainer workouts out of Garmin |
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
| Two copies of a workout in the watch's saved list | An old copy from before a delete. Remove it on the watch |

## After a merge

- A GitHub release `v<version>`, an image `ghcr.io/zimmertr/hevy-garmin-sync:<version>` and a chart `ghcr.io/zimmertr/hevy-garmin-sync-helm` `<version>` that pins the image's digest.
- A PR in Kubernetes-Manifests titled `chore(hevy-garmin-sync): bump chart to <version>`, which merges itself. When it merges, Argo CD replaces the pod with the new release.

| You see | Do |
|---|---|
| The release stopped at a scan | A fixable Critical or High is in the image. The fix is the next release, usually a Dependabot digest PR for the base image |
| `Release / Push Chart` failed | Re-run the failed jobs, not all jobs; a chart already pushed is skipped |
| `Release / Deploy Bump` failed on its `yq` step | The file or the chart entry is missing in Kubernetes-Manifests; restore it, then re-run the failed job |
| The weekly image scan failed | Same as a release scan: ship a fix in the next release |
| An issue "Garmin's exercise list or Hevy's API changed", and a PR `test(upstream): update the copies of Garmin's exercise list and Hevy's API` | The weekly upstream check found a difference. Read the issue for what changed. In the PR, fix any map row its tests flag, add the change, dated, to `docs/DATA.md`, then merge it. The next Monday run force-pushes the PR's branch, so merge before then or keep your fixes in a PR of your own |
| The weekly upstream check failed with no issue | It couldn't fetch or read Garmin's list or Hevy's spec. The run's log says which. Re-run it; if it keeps failing, the source has moved or changed shape, and `scripts/check_upstream.py` needs a fix |
