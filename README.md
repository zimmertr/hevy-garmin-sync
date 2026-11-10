# hevy-garmin-sync

Puts your Hevy routines on your Garmin watch as strength workouts.

## Summary

I plan my lifting in Hevy and record it on a Garmin watch. Garmin forwards the watch's recording to Strava the moment it's saved, and Strava keeps that version, so the only way to get the right exercises, sets and weights onto Strava is to start the session from a planned workout on the watch that already has them. This keeps one Garmin workout for every Hevy routine, and for Hevy Trainer's workouts too if you use Trainer, and sends them to the watch.

## How It Works

It runs as one container. Every minute it checks Hevy for changes, and when a routine changes it updates the matching Garmin workout and sends it to the watch, which picks it up on its next sync with your phone. It reads Hevy and writes Garmin, nothing else: it never writes to Hevy and never touches Strava. [docs/SPEC.md](docs/SPEC.md) has the full design.

## Quick Start

There's nothing to run yet. The sync is being built in [#1](https://github.com/zimmertr/hevy-garmin-sync/issues/1), and this section gets the real steps when it lands.

## Docs

| Doc | What's in it |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | The design, requirement by requirement |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the repo, the image and the chart fit together |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every setting |
| [docs/USAGE.md](docs/USAGE.md) | What you'll see, and what to do when it breaks |
| [docs/DATA.md](docs/DATA.md) | What Hevy and Garmin return, and their quirks |
| [docs/CICD.md](docs/CICD.md) | How a change becomes a release |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Working on the code |

## Support

Open an issue. Security problems go through private reporting instead ([the security policy](https://github.com/zimmertr/hevy-garmin-sync/security/policy)).

## License

[MIT](LICENSE). [NOTICES.md](NOTICES.md) credits the projects it builds on.
