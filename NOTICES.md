# Notices

hevy-garmin-sync itself is licensed under the [MIT License](LICENSE). This file credits the third parties it is built on: the services it talks to, the projects it learned from, and the software bundled into the shipped image.

## Services

- **Hevy** ([hevy.com](https://www.hevy.com)): the public API ([docs](https://api.hevyapp.com/docs)), used under a Hevy Pro API key, and, for Hevy Trainer, the private API the Hevy app uses. Hevy is not affiliated with this project. [docs/DATA.md](docs/DATA.md) describes both.
- **Garmin Connect**: Garmin's unofficial web API. Garmin is not affiliated with this project.

## Projects it learned from

- **[hevy2garmin](https://github.com/drkostas/hevy2garmin)** by drkostas, MIT License: its Hevy-to-Garmin exercise map and its Garmin workout JSON are the references for this project's (spec F-51).

## Bundled in the image

The direct pins in `requirements.in`, with the license of each; a test holds this table to that file. The release's SBOM is the full list, including the Debian packages under the base image ([docs/SBOM.md](docs/SBOM.md)).

| Software | Version | License |
|---|---|---|
| [garminconnect](https://github.com/cyberjunky/python-garminconnect) | 0.3.20 | MIT License |
| [requests](https://github.com/psf/requests) | 2.34.2 | Apache License 2.0 |
| [tzdata](https://github.com/python/tzdata) | 2026.6 | Apache License 2.0 |

From the `python:3.15-slim` base image: Python 3.15 (Python Software Foundation License), pip (MIT License), and Debian 13 (each package's own license; see the SBOM).
