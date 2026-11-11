# Configuration

Every setting, and where it is set. The app reads environment variables only (spec section 11). A missing or invalid one stops it at startup with a message that names the variable and the fix. The README's variable table and this one change together.

## Environment variables

| Variable | Default | Does |
|---|---|---|
| `HEVY_API_KEY` | required | The Hevy public API key, from https://hevy.com/settings?developer. Needs Hevy Pro (C-1) |
| `GARMIN_TOKEN` | required on the first start | The value the `login` command prints. Later starts use the copy in `DATA_DIR`, which the app keeps current as Garmin rotates it. Set a new value to replace that copy (C-2, A-4) |
| `INCLUDE_HEVY_FOLDERS` | unset: every routine | Comma-separated routine folder ids or titles. An id is tried before a title. Routines outside these folders, and routines in no folder, are left out. A name that matches no folder exits at startup, after the folder list is logged. Does not apply to Hevy Trainer (C-3) |
| `CUSTOM_EXERCISE_MAP` | unset: by muscle group and equipment | The Garmin exercise for your own Hevy exercises, as comma-separated `title-or-id=CATEGORY/NAME` entries: `My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE,a1b2c3d4=CURL/CURL`. An id is tried before a title. A title matches exactly, capitals included, once spaces around it are trimmed. An entry splits on its last `=`, so a title may hold one. A title with a comma in it can't be written here: use the exercise's template id. The pair is Garmin's category and exercise keys from [`garmin_exercises.json`](../src/hevy_garmin_sync/data/garmin_exercises.json); the log line `Custom Hevy exercise ...` shows what each custom exercise gets now. A pair Garmin doesn't have, or an entry not in this form, exits at startup. An entry for a built-in Hevy exercise is ignored with a warning: fix those in the exercise map. Applies to Hevy Trainer too (C-11) |
| `ENABLE_SCHEDULED_WORKOUTS` | `true` | `true` puts every routine, and Hevy Trainer's next workout, on today's Garmin calendar. `false` keeps the app off the calendar and removes the entries it made (C-4) |
| `HEVY_SESSION` | unset: Hevy Trainer off | The `auth2.0-token` cookie from hevy.com. Setting it turns Hevy Trainer on. Unsetting it turns Trainer off, removes its Garmin workouts and deletes the stored session (C-5) |
| `HEVY_POLL_INTERVAL_SECONDS` | `60` | How often Hevy is read. A whole number, 10 or more (C-6) |
| `TZ` | the Garmin profile's time zone | Decides "today", midnight, and the start of Trainer's week. A name such as `America/Los_Angeles`. If it is unset and Garmin gives none, UTC with a warning (C-7) |
| `DATA_DIR` | `/data` in the image, `data` from a clone | The one folder the app writes: the rotated Garmin token and Hevy session (C-8) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. `DEBUG` adds per-workout detail and the call count of each poll (C-9) |
| `LOG_FORMAT` | `text` | `text` or `json`, one object per line (C-10) |
| `APP_VERSION` | `0.0.0+dev` | Baked into the image by the release. The version `--version` and the startup log report |

The startup log lists the effective value of each, with the three secrets shown only as set or unset (O-3c), and `CUSTOM_EXERCISE_MAP` only as set with its number of entries, since the entries are your own exercise titles.

## The data folder

| File | Holds |
|---|---|
| `garmin_tokens.json` | Garmin's current tokens |
| `garmin_tokens.json.seed` | A hash of the `GARMIN_TOKEN` value those tokens started from |
| `hevy_session.json` | Hevy's current session, when Trainer is on |
| `hevy_session.json.seed` | A hash of the `HEVY_SESSION` value it started from |

Both services replace the refresh token every time it is used, so the folder must survive a restart. Losing it costs a new `login` (and a new cookie for Trainer), never a duplicate workout: which Garmin workouts are the app's is written in the workouts themselves (F-12).

## Chart values

`charts/hevy-garmin-sync-helm/values.yaml`, with these keys:

| Value | Default | Does |
|---|---|---|
| `image.repository` | `ghcr.io/zimmertr/hevy-garmin-sync` | The image |
| `image.tag` | the chart's `appVersion` | The release the chart was packaged with |
| `existingSecret` | empty | A Secret you made with `HEVY_API_KEY`, `GARMIN_TOKEN` and, for Hevy Trainer, `HEVY_SESSION`. Empty makes one from `secret` |
| `secret` | empty | Those keys, for the Secret the chart makes |
| `env` | empty | Every other variable, as name and value |
| `persistence.size` | `64Mi` | The data volume |
| `persistence.storageClassName` | empty, the cluster's default | Its storage class |
| `persistence.existingClaim` | empty | A claim you made instead of a new one |
| `resources`, `nodeSelector`, `tolerations` | empty | As usual for a pod |
| `podSecurityContext` | uid and gid 1000, `fsGroup` 1000, non-root | Makes the volume writable by the image's user |
| `securityContext` | no privilege escalation, all capabilities dropped, read-only root filesystem | The container's. The app writes only to `/data` (spec O-4) |

The chart sets `DATA_DIR` to `/data` itself.

## Compose

`compose.yaml` runs the same image with a named volume on `/data` and a read-only root filesystem, and reads the variables from a `.env` file beside it. `.env` is ignored by git.
