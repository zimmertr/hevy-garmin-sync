# 0007. A credential rejected while running exits the app at once, as at startup

- Status: Accepted
- Date: 2026-11-10
- Decider: TJ ("I think exiting immediatly is fine as we will run this on K8s with exponential backoff and retries.If any non-k8s users are frustrated they can complain and we will change then.")
- Issues and PRs: #23, #35
- Cited in code as: none
- Guide: none in [`CLAUDE.md`](../../CLAUDE.md); the rule is spec O-1 in [`docs/SPEC.md`](../SPEC.md)

## Context

At startup a rejected `HEVY_API_KEY`, `GARMIN_TOKEN` or `HEVY_SESSION` exited 1 with the fix. While running, the same rejection was logged and retried, one minute doubling to thirty, with no end. The pod stayed `Running`, the chart has no probes, and spec O-2 makes logs the only signal, so a dead token left the watch stale with nothing looking wrong. hevy-trainer-sync, which this app replaced, ran as a CronJob, where a failed run showed as a failed Job.

## Decision

`App._loop`, `App._read_hevy` and `App._read_trainer` treat the first `Rejected` from Garmin, Hevy or Hevy Trainer as `ConfigError`. The app logs one ERROR line with the service and the fix, in the startup check's words, and exits 1. A dead `HEVY_SESSION` exits too, so routines stop syncing until it is fixed or unset. Outages, 5xx, 429, a refused request and unexpected errors still never exit (O-1). The app adds no retry: `HevyPrivate` still refreshes the session and tries once before a rejection reaches the loop.

## Evidence

- 2026-11-10: read in the code at `add2ebd`. Not seen live.
- Spec D-11g counts every 401 and 403 as a rejection, so a 403 that is a temporary block exits too.

## Alternatives rejected

- **Keep running and retry** (the behaviour before): the failure shows only in the log.
- **Exit only after the rejection has lasted some hours**: more code, a new timer, and a dead token goes unseen for that long.
- **A probe or a notification**: spec O-2 and S-3 rule both out.

## Consequences

`tests/test_app.py` holds it: a rejection of each credential while running exits 1 with the fix, and an outage or a rate limit returns 0. The next start fails the startup check and exits again, so Kubernetes shows `CrashLoopBackOff` and restarts the pod on its own delay, which grows to 5 minutes. Each start calls Garmin once; before, the wait topped out at 30 minutes. Docker Compose's `restart: unless-stopped` restarts it on Docker's delay. Revisit if a user outside Kubernetes complains.
