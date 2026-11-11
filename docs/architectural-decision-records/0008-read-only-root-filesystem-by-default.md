# 0008. The container runs with a read-only root filesystem by default, in the chart and in compose.yaml

- Status: Accepted
- Date: 2026-11-10
- Decider: TJ, 2026-11-10, on #30: make it the default, in the chart and in `compose.yaml` (option A).
- Issues and PRs: #30, #33
- Cited in code as: record 0008, in `.github/workflows/pr.yml`
- Guide: [`docs/SPEC.md`](../SPEC.md) O-4

## Context

The app writes only to `DATA_DIR`, but the chart and `compose.yaml` left the rest of the container's filesystem writable. Spec O-4 said a read-only root filesystem must work but was the user's choice. hevy-trainer-sync, the tool this app replaced, ran read-only. Nothing had checked whether python-garminconnect, curl_cffi or Python itself needs `/tmp` or a home folder.

## Decision

- The chart's `securityContext` sets `readOnlyRootFilesystem: true`.
- `compose.yaml` sets `read_only: true`.
- Neither mounts a `/tmp`, since nothing needs one.

## Evidence

- 2026-11-10, the image from `make build`, run with `--read-only` and `--network none` and made-up credentials: `--version` and `--help` ran. The app wrote `garmin_tokens.json` and its seed to `/data`, logged Hevy as unreachable and waited. Garmin's client, run on that token, failed on name resolution only. No error named a read-only filesystem or a path outside `/data`.
- 2026-11-10, the same image, read-only and with no network: python-garminconnect's sign-in with an invented email and password tried all five strategies, curl_cffi's included, and failed on DNS only. `login` gives the library no token store, so it saves no file, and curl_cffi only reads its fingerprint file when one exists.

## Alternatives rejected

- The chart only: Compose users would not get it, and the two ways of running the app would behave differently.
- Leaving it to the user, as O-4 did: a library that starts writing outside `/data` would go unnoticed.

## Consequences

- The `Chart` job and `make chart` check that the default render carries `readOnlyRootFilesystem: true`. The smoke test runs `--version` with `--read-only`.
- A library update that writes elsewhere fails at startup, in the log. The fix is a rollback, or a mounted `/tmp`.
- The release that ships this changes TJ's pod at once: his values leave `securityContext` to the chart.
