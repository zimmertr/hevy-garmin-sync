# hevy-garmin-sync

<img src="src/hevy_garmin_sync/web/icon.svg" alt="" width="96">

Puts your Hevy routines on your Garmin watch as strength workouts.

## Summary

I plan my lifting in Hevy and record it on a Garmin watch. Garmin forwards the watch's recording to Strava the moment it's saved, and Strava keeps that version, so the only way to get the right exercises, sets and weights onto Strava is to start the session from a planned workout on the watch that already has them. This keeps one Garmin workout for every Hevy routine, and for Hevy Trainer's workouts too if you use Trainer, and sends them to the watch.

## How It Works

It runs as one container. Every minute it checks Hevy for changes, and when a routine changes it updates the matching Garmin workout and sends it to the watch, which picks it up on its next sync with your phone. Every routine also sits on today's Garmin calendar, so the watch offers them when you start a strength activity. It reads Hevy and writes Garmin, nothing else: it never writes to Hevy and never touches Strava. [docs/SPEC.md](docs/SPEC.md) has the full design.

What it doesn't do: it doesn't copy finished workouts from Hevy to Garmin, it doesn't touch Garmin workouts it didn't make, and it doesn't pick which routine is next (for Hevy Trainer, today's calendar gets just the workout Hevy says is next).

## Quick Start

You need Hevy Pro (for the API key) and a Garmin watch that runs strength workouts.

### 1. Get a Hevy API key

Make one at https://hevy.com/settings?developer. That's `HEVY_API_KEY`.

### 2. Sign in to Garmin once

```sh
docker run --rm -it ghcr.io/zimmertr/hevy-garmin-sync:0.3.0 login
```

It asks for your Garmin email, password and 2FA code, and prints one long value. That's `GARMIN_TOKEN`. The password is used once and saved nowhere. Run this at home even if you host the app in the cloud: Garmin blocks sign-ins from a lot of cloud IPs. After the first start the app keeps the token current in its data folder, so you only do this again if Garmin signs you out.

### 3. Run it

With Docker Compose, copy [.env.example](.env.example) to `.env`, fill in the two values, and start [compose.yaml](compose.yaml):

```sh
docker compose up -d
```

With Helm:

```sh
helm install hevy-garmin-sync oci://ghcr.io/zimmertr/hevy-garmin-sync-helm --version 0.3.0 \
  --set secret.HEVY_API_KEY=your-key \
  --set secret.GARMIN_TOKEN=your-token \
  --set env.TZ=America/Los_Angeles
```

From a clone:

```sh
make build
docker run --rm -p 127.0.0.1:8080:8080 -v hevy-garmin-sync-data:/data --env-file .env hevy-garmin-sync:dev
```

Run one copy only. Two would refresh the same Garmin token and lock each other out. Keep the `/data` volume: it holds the tokens.

Sync your watch, start a strength activity, and your routines are there.

### The status page

Open http://localhost:8080. It shows every workout and what it became in Garmin, which Garmin exercise each Hevy exercise got, the weights, whether Hevy and Garmin are working, and the log. With Helm it's a ClusterIP Service unless you set `service.type`; `kubectl port-forward svc/hevy-garmin-sync 8080` gets you there either way.

**Sync now** reads Hevy and syncs all workouts to Garmin Connect, and sends them all to the watch again. **Force sync** also overwrites every workout on Garmin Connect, so anything you edited there is gone. You get one a minute. From a terminal it's `sync` (or `sync --force`) inside the container:

```sh
docker compose exec hevy-garmin-sync python3 -m hevy_garmin_sync sync
```

There's no sign-in. Anyone who can reach the port can see your workouts and press the buttons. Compose and the `docker run` above only publish it on your own machine; Docker without `-p` and Helm with a ClusterIP Service don't publish it at all. Run straight from a clone with Python, it listens on your whole network.

### Hevy Trainer

Trainer's program isn't in Hevy's public API, so this reads it from the private API the Hevy app uses, and works out the weights the app would show. Hevy doesn't document that API and can change it, and Hevy's terms allow suspending accounts for unauthorized use. It's off unless you turn it on.

To turn it on, open a private browser window, sign in at hevy.com, and copy the value of the `auth2.0-token` cookie (developer tools, Application, Cookies). Close the window without logging out, and set `HEVY_SESSION` to that value. Don't keep using a browser signed in with that same session: the app and the browser would end each other's session. The Hevy phone app isn't affected.

[docs/HEVY_TRAINER_RULES.md](docs/HEVY_TRAINER_RULES.md) has the rules the weights follow.

### Settings

| Variable | Default | Does |
|---|---|---|
| `HEVY_API_KEY` | required | Your Hevy API key |
| `GARMIN_TOKEN` | required on the first start | What `login` printed |
| `INCLUDE_HEVY_FOLDERS` | every routine | Only these routine folders, by id or title, comma-separated |
| `CUSTOM_EXERCISE_MAP` | by muscle group | The Garmin exercise for your own Hevy exercises, as `title-or-id=CATEGORY/NAME`, comma-separated |
| `ENABLE_SCHEDULED_WORKOUTS` | `true` | Put every routine, and Hevy Trainer's next workout, on today's Garmin calendar |
| `ENABLE_PREVIOUS_VALUES` | `true` | Show last time's sets in each set's note on the watch |
| `HEVY_SESSION` | off | Turns Hevy Trainer on |
| `HEVY_POLL_INTERVAL_SECONDS` | `60` | How often Hevy is checked |
| `TZ` | your Garmin profile's time zone | Decides when "today" starts |
| `DATA_DIR` | `/data` | Where the tokens are kept |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more |
| `LOG_FORMAT` | `text` | Or `json` |
| `HTTP_PORT` | `8080` | The status page's port |

[docs/CONFIGURATION.md](docs/CONFIGURATION.md) has the detail on each.

### Good to know

- A change in Hevy is in Garmin Connect within a minute. The watch gets it at its next sync with your phone.
- A routine you delete in Hevy leaves Garmin Connect, but the copy in the watch's saved workouts stays until you delete it on the watch.
- Don't edit the description of a workout it made. That's how it knows the workout is its own.
- Weights go to Garmin in the unit your Garmin Connect account uses. The watch shows them in its own weight unit, which is a separate setting on the watch.
- Each set's note on the watch lists what you did last time, one set to a line, like `65 x 6 @ 7.5` under `Previous (lb):`. The number after `@` is the RPE. Last time is the last workout you logged that exercise in, any workout, in the past 12 months. It doesn't follow Hevy's "Previous Workout Values" setting. Warm-ups are left out. `ENABLE_PREVIOUS_VALUES=false` turns it off.
- If Hevy or Garmin rejects a sign-in, the app keeps running and the status page says what to fix. With a rejected `HEVY_SESSION`, routines keep syncing.
- A sync costs about 3 Garmin calls per workout, and Garmin blocks accounts that call too often. Press Sync now when something looks wrong, not on a timer.
- If an exercise shows up under the wrong name on the watch, the fix is one line in [the exercise map](src/hevy_garmin_sync/data/exercise_map.csv). Open an issue or a PR. On the status page, an exercise it had to guess has a "Report this match" link that fills the issue in for you.

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

## Support

Open an issue. Security problems go through private reporting instead ([the security policy](https://github.com/zimmertr/hevy-garmin-sync/security/policy)).

## License

[MIT](LICENSE). The exercise map started from [hevy2garmin](https://github.com/drkostas/hevy2garmin)'s, and Garmin is reached through [python-garminconnect](https://github.com/cyberjunky/python-garminconnect). [NOTICES.md](NOTICES.md) credits everything it builds on.
