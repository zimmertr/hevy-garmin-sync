# Contributing

hevy-garmin-sync has one maintainer. For a large change, open an issue first, so the approach gets discussed before you build it.

If you send a change:

- Every check CI runs is a `make` target at the repository root (`make test`, `make lint`, `make typecheck`, `make chart`, `make build`, `make scan`), and each one runs in Docker. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) lists them.
- Every change ships with tests in the same PR. Coverage aims at 100% of lines and branches: CI reports it, and a gap gets a test or a written reason. Tests use `unittest` and `unittest.mock` and never touch the network.
- The PR title is `type(scope): summary`, such as `fix(garmin): keep the rest step after the last set`. The title picks the release version, and the `PR Title` check fails anything else ([docs/CICD.md](docs/CICD.md)).
- The `docs/` page that owns the topic changes in the same PR, and a decision gets a record in [docs/architectural-decision-records/](docs/architectural-decision-records/README.md). The table in `CLAUDE.md` says which page owns what. Behaviour follows [docs/SPEC.md](docs/SPEC.md).
- The repo is public. No tokens, ids or personal data in code, fixtures or logs.

Security problems go through private reporting, not issues ([the security policy](https://github.com/zimmertr/hevy-garmin-sync/security/policy)).
