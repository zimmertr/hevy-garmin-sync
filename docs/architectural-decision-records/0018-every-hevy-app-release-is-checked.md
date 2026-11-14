# 0018. Every Hevy app release is checked for changes to the Trainer rules, outside this repo

- Status: Accepted
- Date: 2026-11-13
- Decider: TJ, in the session that opened #64
- Issues and PRs: #64, #66
- Cited in code as: none
- Guide: [`CLAUDE.md`](../../CLAUDE.md), "Build to the spec"; spec F-48 and D-7b in [`docs/SPEC.md`](../SPEC.md)

## Context

The Hevy app works out Hevy Trainer's weights on the phone, and this app copies those rules from one version of it (`docs/HEVY_TRAINER_RULES.md`). Until now nothing noticed a new version (spec F-48). A weight on the watch that differed from the Hevy app was the only sign, and it showed in the gym. Staying in step with Hevy on progressions and missed targets matters to TJ.

## Decision

Every Hevy release is checked for changes to these rules, patches included. A weekly job outside this repo notices a new version on the App Store and opens the check. The check and how it's done stay out of this public repo (D-7b). A changed rule comes back here as an issue that states the new rule, and the fix follows the usual path: the rules page, the spec and `src/hevy_garmin_sync/trainer_rules.py` in one PR.

## Evidence

- 2026-11-13: of the 29 releases from 3.0.8 to 3.2.7, 8 changed a rule, and 7 of those 8 were patches. Their release notes named 1. Hevy often reuses a release's notes for the patches after it.
- 2026-11-13: no release from 3.2.5, the version the rules were read from, through 3.2.7 changed them.

## Alternatives rejected

- Nothing checks (record 0043 in hevy-trainer-sync): a changed rule shows only once the watch is wrong in the gym.
- Checking only minor and major releases, or only releases whose notes mention Trainer: would have missed 7 of the 8 changes.
- The check in this repo's weekly upstream check (record 0010): a version on its own says nothing about the rules, since about 1 release in 4 changed one. The check that does say keeps out of a public repo.
- Comparing the weights a user logs with what the app predicted: a weight changed on purpose looks like a mismatch.

## Consequences

Nothing in this repo changes for a new Hevy release unless a rule did. The iPhone app's version is what the weekly job watches, since Google Play has no public lookup, so a release can reach Android a few days before the job sees it.
