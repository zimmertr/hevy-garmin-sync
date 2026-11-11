# 0011. A refused workout is retried at growing gaps until midnight, then daily, and a rate limit's own wait beats the app's

- Status: Accepted
- Date: 2026-11-10
- Decider: TJ. On #4: "expontential backoff up to midnight. Then just daily". On #27: honour `Retry-After`, and let the service's wait win over the app's 30 minute cap.
- Issues and PRs: #4, #27, #38
- Cited in code as: #4, #27
- Guide: none in [`CLAUDE.md`](../../CLAUDE.md); the rules are spec F-16 and O-1 in [`docs/SPEC.md`](../SPEC.md)

## Context

A workout Garmin refused was skipped until its routine changed in Hevy, the app restarted, or local midnight came (F-16, TJ, 2026-11-07, for the first version). A refusal Garmin would have accepted ten minutes later still waited for midnight. Retrying on every poll was ruled out: about 1,440 refused calls a day for one bad workout, and Garmin blocks accounts that call too often (F-4a). Separately, a 429's `Retry-After` header was thrown away, and the app used its own waits: 1 minute doubling to 30, and 15 minutes first after a Garmin 429 (O-1).

## Decision

`Sync._write` keeps a record for each refused workout version: its local day, its current gap, and when it is next due. A poll tries it only once it is due; until then the poll calls Garmin for nothing (F-4a). The first gap is 5 minutes, and each refusal doubles it. The full run at local midnight tries every refused workout; one refused there is tried only by full runs from then on, which is once a day unless a Garmin failure forces another full run. Every full run tries every refused workout. A changed version is tried at once and starts over at 5 minutes. A success drops the record. The record is in memory only: a restart tries each workout at startup and starts its gaps over, which TJ accepted in #4.

`errors.retry_after` reads `Retry-After` as whole seconds or an HTTP date, and gives None for a missing value or one that is neither. `get_json` (Hevy and Hevy Trainer) and `Garmin._call` put it on `RateLimited.retry_after`. `Backoff.failed` waits that long when it is there, even past the 30 minute cap, but never less than the poll interval, so `Retry-After: 0` can't become a burst of calls. Without it, the waits are as before. The ERROR line says that the service said how long to wait, and how long the app will.

## Evidence

- 2026-11-10: a workout always refused is tried at most 8 more times before its first midnight (gaps of 5 to 640 minutes from 00:00 end at 21:15), then once a day. `tests/test_sync.py` runs that day minute by minute.
- 2026-11-10, read in python-garminconnect 0.3.20's source: a read's 429 is raised as `GarminConnectTooManyRequestsError` from the library's `GarminConnectConnectionError`, which holds the `requests` reply; a write's 429 is that `GarminConnectConnectionError` with the reply on `.response`; a 429 on the token exchange has no reply, so it keeps the 15 minute wait.
- No dated measurement of either service's 429: neither has been seen sending one to this app, and hevy-trainer-sync's records say it never got one (2026-11-10). Garmin has not been seen refusing one of the app's workouts.

## Alternatives rejected

- **Retry a refused workout once, an hour later** (#4, option B): the least code, but slower to recover.
- **Retry on every poll**: up to about 1,440 refused calls a day for one workout (F-4a).
- **Keep the record in `DATA_DIR`** so a restart remembers it: one extra try at each start costs one call, and a file would need the write-temp, fsync, rename care of O-3a.
- **Cap `Retry-After` at 30 minutes**: TJ chose that the service's wait wins (#27).

## Consequences

`tests/test_sync.py` (`RefusedTest`), `tests/test_app.py` (`BackoffTest`, `FailureTest`), `tests/test_hevy.py`, `tests/test_hevy_private.py`, `tests/test_garmin.py` and `tests/test_errors.py` hold it. The cost is at most 8 extra Garmin calls on the first day for each refused workout, then 1 a day. After a rate limit that asks for a long wait, changes in Hevy reach Garmin only once that wait ends, even past 30 minutes. A newer python-garminconnect that stops attaching the reply would quietly bring back the app's own waits; the Garmin tests build the library's errors in the 0.3.20 shapes, so they would not notice.
