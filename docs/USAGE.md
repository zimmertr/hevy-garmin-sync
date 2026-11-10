# Usage

What TJ sees, and what to do when it breaks. Today the image only reports its version; the sync arrives with #1.

## After a merge

- A GitHub release `v<version>`, an image `zimmertr/hevy-garmin-sync:<version>` and a chart `hevy-garmin-sync-helm` `<version>` on Docker Hub.
- A PR in Kubernetes-Manifests titled `chore(hevy-garmin-sync): bump chart to <version>`, which merges itself. Nothing deploys while the folder is `misc/hevy-garmin-sync.disabled`.

## When it breaks

| You see | Do |
|---|---|
| The release stopped at a scan | A fixable Critical or High is in the image. The fix is the next release, usually a Dependabot digest PR for the base image |
| `Publish OCI chart` failed | Re-run the failed jobs; a chart already pushed is skipped |
| `Bump Kubernetes-Manifests` failed on its `yq` step | The file or the chart entry is missing in Kubernetes-Manifests; restore it, then re-run the failed job |
| The weekly image scan failed | Same as a release scan: ship a fix in the next release |
