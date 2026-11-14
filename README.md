# hevy-garmin-sync

<img src="src/hevy_garmin_sync/web/icon.svg" alt="" width="96">

Puts your Hevy routines on your Garmin watch as strength workouts.

## Summary

I plan my lifting in Hevy and record it on a Garmin watch. This keeps one Garmin Connect workout for every Hevy routine, and for Hevy Trainer's workouts too if you use Trainer, and sends them to the watch. Start a strength activity from one of them and the watch records the right exercises, sets and weights. Garmin then forwards that recording to Strava, so Strava gets them right too, which is what I was after.

It reads Hevy and writes Garmin, nothing else: it never writes to Hevy, never touches a Garmin workout it didn't make, and never talks to Strava. [docs/SPEC.md](docs/SPEC.md) has the full design.

![The status page, with five routines, a Hevy Trainer program and one workout Garmin refused](docs/screenshot.png)

## How It Works

It runs as one container. Every minute it checks Hevy for changes, and when something changes it updates the matching Garmin workout and sends it to the watch, which picks it up at its next sync with your phone.

### Routines and folders

Every Hevy routine becomes one Garmin Connect workout: `Hevy: Full Body` for a routine in no folder, `Hevy/Push Pull Legs: Push` for one in a folder. Every routine also sits on today's Garmin calendar, so the watch offers them when you start a strength activity. You can sync only some folders, or keep it off the calendar ([Configuration](#configuration)).

A routine you delete in Hevy leaves Garmin Connect and the calendar. Each workout's description marks it as the app's, so don't edit it: without it the app no longer knows the workout and makes a new one.

### Hevy Trainer

If you turn Trainer on, every workout in your Trainer program becomes one too, named like the Hevy app shows it: `Hevy/Trainer: Upper (C2-W2)`, with the cycle and the week. Only the one Hevy says is next goes on today's calendar. When that changes in Hevy, because you logged one or reordered them, the calendar follows within a minute. The others are in the watch's saved workouts.

Trainer's weights aren't in anything Hevy publishes, so the app works them out the way the Hevy app does, from the rules in [docs/HEVY_TRAINER_RULES.md](docs/HEVY_TRAINER_RULES.md). That's a best guess. Hevy can change its rules in any update, and the weights would drift. If a weight or rep range on the watch doesn't match the Hevy app, open an issue with both.

### Exercises

Garmin only takes exercises from its own list, so every Hevy exercise is matched to a Garmin one. For Hevy's built-in exercises the match is a row in [the exercise map](src/hevy_garmin_sync/data/exercise_map.csv). For your own Hevy exercises it's the closest Garmin exercise by the muscle group and equipment you set in Hevy (more under [Known Limitations and Problems](#known-limitations-and-problems)).

If an exercise shows up under the wrong name on the watch, the fix is one line in the map. Open an issue or a PR. On the status page, an exercise it had to guess has a "Report this match" link that fills the issue in for you.

### The notes screen

Each set has a note on the watch, one page down from the main screen during the set. It shows the set the way the watch's set-info screen does, under Hevy's name for the set type:

```
Warm Up Set
4-6 Reps
35 lbs
Hevy: Seal Row (Dumbbell)
```

The type is `Warm Up Set`, `Normal Set`, `Failure Set` or `Drop Set`. The target is the reps, a time such as `0:30`, or a distance. The last line is Hevy's name for the exercise, only when Garmin calls it something else.

Weights go to Garmin in the unit your Garmin Connect account uses. The watch shows them in its own weight unit, which is a separate setting on the watch.

## Requirements

- Hevy Pro, for the API key.
- A Garmin watch that runs strength workouts.
- Docker, or a Kubernetes cluster with Helm.

## Instructions

### 1. Get a Hevy API key

Make one at https://hevy.com/settings?developer. That's `HEVY_API_KEY`.

### 2. Sign in to Garmin once

Set `VERSION` to the newest release on the [Releases page](https://github.com/zimmertr/hevy-garmin-sync/releases), then:

```sh
VERSION=x.y.z
docker run --rm -it "ghcr.io/zimmertr/hevy-garmin-sync:$VERSION" login
```

It asks for your Garmin email, password and 2FA code, and prints one long value. That's `GARMIN_TOKEN`. The password is used once and saved nowhere. Run this at home even if you host the app in the cloud: Garmin blocks sign-ins from a lot of cloud IPs. After the first start the app keeps the token current in its data folder, so you only do this again if Garmin signs you out.

### 3. Run it

With Docker Compose, download [compose.yaml](compose.yaml) and [.env.example](.env.example) into an empty folder:

```sh
curl -fsSLO https://raw.githubusercontent.com/zimmertr/hevy-garmin-sync/main/compose.yaml
curl -fsSL https://raw.githubusercontent.com/zimmertr/hevy-garmin-sync/main/.env.example -o .env
```

In `.env`, set `HEVY_GARMIN_SYNC_VERSION` to the newest release, fill in the two values, and start it:

```sh
docker compose up -d
```

With Helm, put the two values in a Secret, and the rest in a values file:

```sh
kubectl create secret generic hevy-garmin-sync \
  --from-literal=HEVY_API_KEY=your-key \
  --from-literal=GARMIN_TOKEN=your-token
```

```yaml
# values.yaml
existingSecret: hevy-garmin-sync
env:
  TZ: America/Los_Angeles
persistence:
  size: 64Mi
```

```sh
helm install hevy-garmin-sync oci://ghcr.io/zimmertr/hevy-garmin-sync-helm -f values.yaml
```

With no `--version`, Helm installs the newest release. [docs/CONFIGURATION.md](docs/CONFIGURATION.md#chart-values) has every chart value.

Run one copy only. Two would refresh the same Garmin token and lock each other out. Keep the data volume: it holds the tokens.

### 4. Check it works

`docker compose logs -f`, or `kubectl logs -f deploy/hevy-garmin-sync`. Within a minute you should see each of your routine folders, then a summary of the first sync:

```
INFO hevy_garmin_sync.routines Hevy routine folder: id 42, title 'Push Pull Legs'
INFO hevy_garmin_sync.app Sync: created 6, updated 0, deleted 0, scheduled 5, unscheduled 0, failed 0
```

The workouts are in Garmin Connect now. Sync your watch with your phone, start a strength activity, and your routines are there.

### The status page

Open http://localhost:8080. It shows every workout and what it became in Garmin, which Garmin exercise each Hevy exercise got, the weights, whether Hevy and Garmin are working, and the log. With Helm it's a ClusterIP Service unless you set `service.type`; `kubectl port-forward svc/hevy-garmin-sync 8080` gets you there either way.

**Sync now** reads Hevy and syncs all workouts to Garmin Connect, and sends them all to the watch again. **Force sync** also overwrites every workout on Garmin Connect, so anything you edited there is gone. You get one a minute. From a terminal it's `sync` (or `sync --force`) inside the container:

```sh
docker compose exec hevy-garmin-sync python3 -m hevy_garmin_sync sync
```

A sync costs about 3 Garmin calls per workout, and Garmin blocks accounts that call too often. Press Sync now when something looks wrong, not on a timer.

There's no sign-in. Anyone who can reach the port can see your workouts and press the buttons. Compose only publishes it on your own machine, and Helm with a ClusterIP Service doesn't publish it at all.

### Keeping it running

To move to a new release with Compose, set `HEVY_GARMIN_SYNC_VERSION` in `.env` to it and run `docker compose up -d` again. With Helm:

```sh
helm upgrade hevy-garmin-sync oci://ghcr.io/zimmertr/hevy-garmin-sync-helm -f values.yaml
```

If Hevy or Garmin rejects a sign-in, the app keeps running and the status page says what to fix. When it's Garmin, run `login` again (step 2), set `GARMIN_TOKEN` to the new value, and restart the app. With a rejected `HEVY_SESSION`, routines keep syncing.

[docs/USAGE.md](docs/USAGE.md) has every log line and what to do about each.

## Configuration

| Variable | Default | Does |
|---|---|---|
| `HEVY_API_KEY` | required | Your Hevy API key |
| `GARMIN_TOKEN` | required on the first start | What `login` printed |
| `INCLUDE_HEVY_FOLDERS` | every routine | Only these routine folders, by id or title, comma-separated |
| `CUSTOM_EXERCISE_MAP` | by muscle group | The Garmin exercise for your own Hevy exercises, as `title-or-id=CATEGORY/NAME`, comma-separated |
| `ENABLE_SCHEDULED_WORKOUTS` | `true` | Put every routine, and Hevy Trainer's next workout, on today's Garmin calendar |
| `ENABLE_PREVIOUS_VALUES` | `true` | Show last time's sets for each exercise on the status page |
| `HEVY_SESSION` | off | Turns Hevy Trainer on |
| `HEVY_POLL_INTERVAL_SECONDS` | `60` | How often Hevy is checked |
| `TZ` | your Garmin profile's time zone | Decides when "today" starts |
| `DATA_DIR` | `/data` | Where the tokens are kept |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more |
| `LOG_FORMAT` | `text` | Or `json` |
| `HTTP_PORT` | `8080` | The status page's port |
| `PREVIEW_PR` | off | Runs on made-up workouts for a pull request's preview, and ignores your keys |
| `PREVIEW_COMMIT` | none | The commit a preview's banner shows |

With Compose they go in `.env`. With Helm the three secrets go in the Secret and the rest under `env:` in `values.yaml`. [docs/CONFIGURATION.md](docs/CONFIGURATION.md) has the detail on each.

### Only some folders

At startup the log lists every routine folder with its id:

```
Hevy routine folder: id 42, title 'Push Pull Legs'
Hevy routine folder: id 43, title 'Home'
```

Name the ones you want, by id or title. Routines in no folder are left out too.

```sh
INCLUDE_HEVY_FOLDERS=Push Pull Legs,43
```

### Keep it off the calendar

```sh
ENABLE_SCHEDULED_WORKOUTS=false
```

The workouts stay in the watch's saved list, and the calendar entries it made are removed.

### Your time zone

```sh
TZ=America/Los_Angeles
```

It decides when "today" starts, for the calendar and for Trainer's week. Unset, it uses the time zone in your Garmin profile.

### Your own exercises

The log says which Garmin exercise each of your own Hevy exercises got:

```
Custom Hevy exercise 'My Cable Raise' (muscle group shoulders, equipment cable) is Garmin's TOTAL_BODY / TOTAL_BODY, by muscle group and equipment
```

To pick a different one, find its category and name in [garmin_exercises.json](src/hevy_garmin_sync/data/garmin_exercises.json) and set:

```sh
CUSTOM_EXERCISE_MAP=My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE
```

### Hevy Trainer

Trainer's program isn't in Hevy's public API, so this reads it from the private API the Hevy app uses. Hevy doesn't document that API and can change it, and Hevy's terms allow suspending accounts for unauthorized use. It's off unless you turn it on.

To turn it on, open a private browser window, sign in at hevy.com, and copy the value of the `auth2.0-token` cookie (developer tools, Application, Cookies). Close the window without logging out, and set `HEVY_SESSION` to that value. Don't keep using a browser signed in with that same session: the app and the browser would end each other's session. The Hevy phone app isn't affected.

## Docs

| Doc | What's in it |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | The design, requirement by requirement |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the code, the image and the chart fit together |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every setting |
| [docs/USAGE.md](docs/USAGE.md) | What you'll see, and what to do when it breaks |
| [docs/DATA.md](docs/DATA.md) | What Hevy and Garmin return, and their quirks |
| [docs/HEVY_TRAINER_RULES.md](docs/HEVY_TRAINER_RULES.md) | How Hevy Trainer's weights are worked out |
| [docs/CICD.md](docs/CICD.md) | How a change becomes a release |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Working on the code |

## Known Limitations and Problems

- **An exercise swapped for one session doesn't reach the watch.** When you replace an exercise in Hevy and answer "Replace permanently?" with No, Hevy keeps that swap on your phone until you save the workout, so the watch keeps the old exercise ([#44](https://github.com/zimmertr/hevy-garmin-sync/issues/44)). To do the new exercise from the watch, answer Yes, which reaches Garmin within a minute, and swap back after the session.
- **Your own Hevy exercises don't keep their names.** Garmin only takes exercises from its own list, so the name you gave one in Hevy can't reach the watch, Garmin Connect or Strava. It shows as the closest Garmin exercise by the muscle group and equipment you set in Hevy: a biceps exercise with dumbbells shows as Dumbbell Biceps Curl, and one with a muscle group the app doesn't know shows as Core. `CUSTOM_EXERCISE_MAP` picks a different one ([Your own exercises](#your-own-exercises)).
- **Trainer's weights are worked out, not read.** They can drift when Hevy changes its rules ([Hevy Trainer](#hevy-trainer)).
- **A deleted routine stays on the watch.** It leaves Garmin Connect, but the copy in the watch's saved workouts stays until you delete it on the watch.
- **The watch only gets changes when it syncs.** A change in Hevy is in Garmin Connect within a minute, and on the watch at its next sync with your phone.
- **It doesn't copy finished workouts** from Hevy to Garmin, and it doesn't pick which routine is next. For Hevy Trainer, today's calendar gets just the workout Hevy says is next.

## Support

Open an issue. Security problems go through private reporting instead ([the security policy](https://github.com/zimmertr/hevy-garmin-sync/security/policy)).

## License

[MIT](LICENSE). The exercise map started from [hevy2garmin](https://github.com/drkostas/hevy2garmin)'s, and Garmin is reached through [python-garminconnect](https://github.com/cyberjunky/python-garminconnect). [NOTICES.md](NOTICES.md) credits everything it builds on.
