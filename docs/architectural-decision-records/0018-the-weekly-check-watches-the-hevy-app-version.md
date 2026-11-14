# 0018. The weekly upstream check watches the Hevy app's version, and a new one waits for the rules to be checked

- Status: Accepted
- Date: 2026-11-13
- Decider: TJ, choosing option B of three in the session that opened #64
- Issues and PRs: #64
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-48 in [`docs/SPEC.md`](../SPEC.md)

## Context

The Hevy app works out Hevy Trainer's weights on the phone, and this app copies those rules from one version of it (`docs/HEVY_TRAINER_RULES.md`). Until now nothing noticed a new version (spec F-48): a weight on the watch that differed from the Hevy app was the only sign. Staying in step with Hevy on progressions and missed targets matters to TJ.

## Decision

`scripts/check_upstream.py` reads the Hevy app's version from Apple's public App Store lookup and compares it with `tests/data/hevy_app_version.json`. A new version opens the weekly check's issue and PR like any other difference. The rules are checked against the new app by hand, and the PR that moves the version merges only then.

## Evidence

- 2026-11-13: Apple's lookup for app 1458862350, `com.hevyapp.hevy`, gave version 3.2.6, released 2026-11-10. The rules were read from 3.2.5.
- 2026-11-13: Hevy's terms (https://www.hevyapp.com/terms/) say nothing on version checks; the lookup is Apple's, public, and needs no sign-in.

## Alternatives rejected

- Nothing checks (record 0043 in hevy-trainer-sync): a changed rule shows only once the watch is wrong in the gym.
- Decompiling each new app and comparing the rules in CI: needs an APK source outside Google Play, and a public repo would publish how the rules were found (spec D-7b).
- Comparing the weights a user logs with what the app predicted: a weight changed on purpose looks like a mismatch.

## Consequences

`tests/test_check_upstream.py` pins the lookup's reading and the comparison. The iPhone app's version stands in for Android's, which Google Play offers no lookup for; they could differ. Hevy ships often, so the issue may come up most weeks. If it gets noisy, this check can go, or the CI comparison can be looked at again (TJ, 2026-11-13).
