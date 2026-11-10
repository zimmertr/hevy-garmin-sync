# Data

Each upstream service, its terms, and every quirk found, dated. The spec's [section 10](SPEC.md#10-known-api-facts-verified-unless-marked) and its watch tests (F-21a, F-20a, F-27, F-30, F-31a) hold the facts verified before the build; move them here, dated, as #1 relies on them.

## Hevy

- **Public API** (`https://api.hevyapp.com/v1`, header `api-key`): routines, routine folders, exercise templates, workouts and workout events. Needs a Hevy Pro API key from Hevy's settings. Documented at https://api.hevyapp.com/docs.
- **Private API**, Hevy Trainer only: the API the Hevy app and web use, undocumented, signed in with the `auth2.0-token` cookie from hevy.com. Hevy can change it without notice. Hevy's terms allow suspending accounts for unauthorized use, and the README says so.

## Garmin Connect

Garmin's unofficial web API, through [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) (MIT) once #1 adds it. Garmin's official APIs don't fit: the personal API key is read-only, and the Training API needs business access (spec section 1). Garmin may block sign-ins from cloud IPs and accounts that call too often.

## Quirks

None recorded here yet. The spec's dated findings come first.
