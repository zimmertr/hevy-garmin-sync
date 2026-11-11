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
| [0002](0002-ci-on-yggdrasil-modules.md) | CI runs on zimmertr/yggdrasil's modules, pinned to the versions a live consumer runs | 2026-11-07 | Accepted |
| [0003](0003-docker-hub-until-yggdrasil-has-ghcr.md) | The image and the chart are published to Docker Hub until yggdrasil adds GHCR | 2026-11-07 | Accepted |
| [0004](0004-bump-a-disabled-folder-until-cutover.md) | Releases bump a disabled Kubernetes-Manifests folder until TJ's cutover | 2026-11-07 | Superseded by 0005 |
| [0005](0005-releases-deploy-through-the-live-folder.md) | Since the cutover, every release bumps the live Kubernetes-Manifests folder and so deploys | 2026-11-10 | Accepted |
