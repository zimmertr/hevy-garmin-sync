# Usage

What you see when it runs, and what to do when it breaks.

## In Garmin Connect and on the watch

- One strength workout per Hevy routine: `Hevy: {routine}` for a routine in no folder, `Hevy/{folder}: {routine}` for one in a folder.
- With Hevy Trainer on, one per Trainer workout: `Hevy/Trainer: Upper (C2-W2)`, with the cycle and week the Hevy app shows.
- Each has a four-line description that marks it as the app's. Don't edit it: without it the app no longer knows the workout and makes a new one.
- Every workout is on today's calendar, so the watch offers them when you start a strength activity. A Trainer workout already logged this week is not on the calendar, but stays in the watch's saved workouts.
- A change in Hevy reaches Garmin Connect within a minute, and the watch at its next sync with your phone.
- A routine deleted in Hevy leaves Garmin Connect and the calendar. The copy in the watch's saved workout list stays until you delete it on the watch.

## In the log

| Line | Means |
|---|---|
| `Sync: created 2, updated 0, deleted 0, scheduled 2, unscheduled 0, failed 0` | One per full run, and one per poll that changed something |
| `Nothing changed in the last hour (60 polls)` | The app is alive and Hevy didn't change |
| `Hevy routine folder: id 42, title 'Push Pull Legs'` | At startup, every folder, for `INCLUDE_HEVY_FOLDERS` |
| `Hevy Trainer: Side Bend (Dumbbell): 40 lbs (up)` | A Trainer prescription, logged when it is first worked out and when it changes |
| `Hevy Trainer: ...: no prescription (...)` | Trainer gives that exercise no weight, and why |

## When it breaks

| You see | Do |
|---|---|
| It exits at startup naming a variable | Fix that variable. The message says how |
| The pod is in `CrashLoopBackOff`, or `docker compose ps` shows it restarting | A sign-in was rejected. The last line of the log says which one, and the rows below say what to do. Nothing syncs until it is fixed; each restart exits again |
| `Garmin rejected the app's credentials` | Run `login` again and set `GARMIN_TOKEN` to the new value |
| `Hevy rejected the app's credentials; check HEVY_API_KEY` | Make a new key at https://hevy.com/settings?developer. The key needs Hevy Pro |
| `Hevy Trainer rejected the app's credentials` | Copy the `auth2.0-token` cookie from hevy.com again, in a private window you then close without logging out, and set `HEVY_SESSION` to it. To sync routines only meanwhile, unset `HEVY_SESSION`, which also takes the Trainer workouts out of Garmin |
| `... can't be reached or is failing ... Trying again in N min` | Nothing. It retries by itself, waiting longer each time, up to 30 minutes |
| `Garmin is rate limiting the app` | Nothing. It waits at least 15 minutes |
| `Garmin refused '<workout>' (N steps)` | Garmin won't take that one workout. The others still sync. It is tried again when the routine changes, at the next start and at midnight. Open an issue with the line |
| `No exercise map row for Hevy exercise ...` | A built-in Hevy exercise the map doesn't know. It still syncs, under the closest exercise by muscle group. Open an issue so it gets a proper row |
| `'<folder>' in INCLUDE_HEVY_FOLDERS is gone` | The folder was renamed or deleted in Hevy. Its workouts are kept. Fix the variable and restart |
| A workout shows the wrong exercise name on the watch | The map has a poor row for it. Open an issue or a PR against `src/hevy_garmin_sync/data/exercise_map.csv` |
| Two copies of a workout in the watch's saved list | An old copy from before a delete. Remove it on the watch |

## After a merge

- A GitHub release `v<version>`, an image `ghcr.io/zimmertr/hevy-garmin-sync:<version>` and a chart `ghcr.io/zimmertr/hevy-garmin-sync-helm` `<version>` that pins the image's digest.
- A PR in Kubernetes-Manifests titled `chore(hevy-garmin-sync): bump chart to <version>`, which merges itself. When it merges, Argo CD replaces the pod with the new release.

| You see | Do |
|---|---|
| The release stopped at a scan | A fixable Critical or High is in the image. The fix is the next release, usually a Dependabot digest PR for the base image |
| `Publish OCI chart` failed | Re-run the failed jobs; a chart already pushed is skipped |
| `Bump Kubernetes-Manifests` failed on its `yq` step | The file or the chart entry is missing in Kubernetes-Manifests; restore it, then re-run the failed job |
| The weekly image scan failed | Same as a release scan: ship a fix in the next release |
