# 0014. Renovate keeps dependencies current, under yggdrasil's shared preset

- Status: Accepted. Supersedes 0002 in part
- Date: 2026-11-11
- Decider: TJ, 2026-11-11, on zimmertr/yggdrasil#40: "I am tempted to switch everything and just define it in yggdrasil and import it into the child repos", then "I agree, lets do it." On the wait: "Lets make sure everything has at least a 1-week cooldown then."
- Issues and PRs: zimmertr/yggdrasil#40, zimmertr/yggdrasil#90

## Context

[0002](0002-ci-on-yggdrasil-modules.md) had Dependabot open the update PRs, with yggdrasil's `auto-merge` module arming a merge on each patch and minor. Dependabot recompiled the two hashed locks itself. TJ then moved every repo to Renovate, with the rules they share written once in yggdrasil's `defaults/renovate.json` (its record 0056).

## Decision

- `.github/renovate.json` extends `github>zimmertr/yggdrasil//defaults/renovate`. The preset holds the seven-day wait, the rule that everything below a major merges itself, and the rule that yggdrasil's own modules don't wait.
- Renovate's `pip-compile` manager reads `requirements.txt` and `requirements-dev.txt`. It takes the command from each lock's header, bumps the pin in the `.in` file and recompiles every lock that depends on it. `pip_requirements` is off, so nothing bumps a lock's pin without its hashes.
- The manager's `lockFileMaintenance` is off (TJ, 2026-11-11). It would open a PR that moves every indirect pin to its newest release at once, with no seven-day wait.
- `make lock` pins pip-tools 7.6.2, and both locks are recompiled with it.
- `ghcr.io/zimmertr/hevy-garmin-sync` is off, so the version in `compose.yaml` moves by hand with the README's.
- `.github/dependabot.yml` and `dependabot-auto-merge.yml` are gone. Dependabot's alerts and security updates stay on.

## Evidence

- 2026-11-11: Renovate's `pip-compile` manager refuses a header option it doesn't know (`Option --no-index not supported (yet)`, in its `common.ts`). Both locks carried `--no-index`. In `python:3.14-slim`, pip-tools 7.5.3 with click 8.5.1 wrote it; pip-tools 7.6.2 with pip 26.3 didn't, and the rest of each lock came out the same, byte for byte.
- 2026-11-11: Renovate 44.221.6, run against this repo in its own image with `--platform=local`, listed `requirements.in` with the lock files `requirements.txt` and `requirements-dev.txt`, and `requirements-dev.in` with `requirements-dev.txt`. It held ruff 0.17.4, six days old, as pending. That run looks updates up and opens nothing, so a recompiled lock from Renovate itself is still unseen.
- The same run proposed `compose.yaml`'s image from 0.3.0 to 0.8.3 as a minor, which would merge itself.

## Alternatives rejected

- Keeping Dependabot for the pip locks alone: two bots and two sets of rules, and the auto-merge module with its `AUTO_MERGE_PAT` kept alive for one ecosystem.
- Moving the locks to `uv pip compile`: a change of tool for the image and the tests, when the newer pip-tools already writes a header Renovate reads.
- Letting Renovate bump `compose.yaml`: every release would open a PR that merges itself and releases again.

## Consequences

- A pin in `requirements.in` moves both locks in one PR. `test_the_dev_lock_installs_what_the_image_installs` fails a PR that moves only one.
- A lock compiled with an older pip-tools gets `--no-index` back, and `test_renovate_can_read_each_locks_header` fails it.
- A Renovate merge is a release that deploys, as a Dependabot merge was ([0005](0005-releases-deploy-through-the-live-folder.md)).
- The `AUTO_MERGE_PAT` secret is unused.
