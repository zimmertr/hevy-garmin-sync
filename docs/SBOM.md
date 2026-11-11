# Software bill of materials

The SBOM is generated, never written by hand.

- **Where:** every release's image carries an SBOM attestation, made by BuildKit when yggdrasil's release module builds it (`sbom: true`), with provenance (`mode=max`). Read it with `docker buildx imagetools inspect ghcr.io/zimmertr/hevy-garmin-sync:<version> --format '{{ json .SBOM }}'`.
- **What it lists:** every package in the image, the Debian packages from the base image included, with versions and licenses.
- **Licenses to watch:** [NOTICES.md](../NOTICES.md) credits each direct dependency with its license, and a test holds that table to `requirements.in`.
