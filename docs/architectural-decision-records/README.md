# Architectural decision records

One file for each design decision: what was decided, when, who decided, and the evidence that settled it. A record sits beside the `CLAUDE.md` rule that states the decision today and does not replace it. The guide tells a session what to do. The record keeps why, and since when.

## Write a record

- Copy [`0000-template.md`](0000-template.md) to `NNNN-slug.md` with the next free number. Numbers have four digits and are never reused. The slug is the decision in a few lowercase words joined by hyphens.
- The title is the decision, as one sentence.
- Take the date and the decider from the conversation or issue that settled it, quoting the decider where the words exist. When nothing records them, use the merge date and the author of the PR that shipped it, and say that git is the source.
- Give every observation the date it was made.
- `Cited in code as` lists the issue and PR numbers that source comments cite for the decision, so a search for `#20` finds the record and the code together.
- Link the record from its `CLAUDE.md` rule as ` Record: [NNNN](docs/architectural-decision-records/NNNN-slug.md)`, right after the sentence that states the decision.
- A decision ships in the same PR as its record. A PR that makes a decision without one is not done.

## Cite a record

A record is evidence, not authority. Cite it for its measurements and its reasons, never as a rule that forbids a change. When today's facts call for a different answer, the new judgement is a superseding record. The maintainer, 2026-10-21: "We only make decisions based on technical problems and UX. Not old ADRs."

## Supersede a record

A new record that reverses an old one says `Supersedes NNNN` in its status line. The old record changes its status line to `Superseded by NNNN` and nothing else. The `CLAUDE.md` link moves to the new record in the same PR.

## Index

| Record | Decision | Date | Status |
|---|---|---|---|
| [0001](0001-build-to-the-signed-off-spec.md) | Build hevy-garmin-sync to the signed-off spec, one direction only, in one repo with its chart | 2026-11-07 | Accepted |
| [0002](0002-ci-on-yggdrasil-modules.md) | CI runs on zimmertr/yggdrasil's modules, pinned to the versions a live consumer runs | 2026-11-07 | Accepted. Superseded in part by 0012 and 0014 |
| [0003](0003-docker-hub-until-yggdrasil-has-ghcr.md) | The image and the chart are published to Docker Hub until yggdrasil adds GHCR | 2026-11-07 | Superseded by 0006 |
| [0004](0004-bump-a-disabled-folder-until-cutover.md) | Releases bump a disabled Kubernetes-Manifests folder until TJ's cutover | 2026-11-07 | Superseded by 0005 |
| [0005](0005-releases-deploy-through-the-live-folder.md) | Since the cutover, every release bumps the live Kubernetes-Manifests folder and so deploys | 2026-11-10 | Accepted |
| [0006](0006-ghcr-and-a-digest-pinned-chart.md) | The image and the chart are in GHCR, and the chart pins the image's digest | 2026-11-10 | Accepted |
| [0007](0007-exit-on-a-credential-rejected-while-running.md) | A credential rejected while running exits the app at once, as at startup | 2026-11-10 | Accepted |
| [0008](0008-read-only-root-filesystem-by-default.md) | The container runs with a read-only root filesystem by default, in the chart and in compose.yaml | 2026-11-10 | Accepted |
| [0009](0009-only-the-next-trainer-workout-on-today.md) | Only the Hevy Trainer workout Hevy says is next is on today, and the calendar follows it within a poll | 2026-11-10 | Accepted |
| [0010](0010-a-weekly-check-of-the-upstream-copies.md) | A weekly check compares Garmin's exercise list and Hevy's API spec with their copies, and on a difference opens one issue and one PR | 2026-11-10 | Accepted |
| [0011](0011-retry-refused-workouts-and-honour-retry-after.md) | A refused workout is retried at growing gaps until midnight, then daily, and a rate limit's own wait beats the app's | 2026-11-10 | Accepted |
| [0012](0012-the-chart-goes-through-yggdrasils-modules.md) | The chart is checked, pushed and deployed by yggdrasil's modules | 2026-11-11 | Accepted. Supersedes 0002 in part |
| [0013](0013-custom-exercises-set-by-one-variable.md) | A custom exercise's Garmin exercise is logged, and one variable, CUSTOM_EXERCISE_MAP, can set it | 2026-11-10 | Accepted |
| [0014](0014-renovate-under-yggdrasils-preset.md) | Renovate keeps dependencies current, under yggdrasil's shared preset | 2026-11-11 | Accepted. Supersedes 0002 in part |
