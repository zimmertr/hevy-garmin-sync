# Configuration

Every setting, and where it is set. Today the image reads only the two below; every variable the app will read is specified in [SPEC.md section 11](SPEC.md#11-configuration-environment-variables-only), and moves here as #1 builds it.

## Environment variables

| Variable | Default | Set by | Does |
|---|---|---|---|
| `APP_VERSION` | `0.0.0+dev` | The release, as a build argument baked into the image | The version `--version` reports |
| `DATA_DIR` | `/data` in the image | The image; the chart sets it too | The folder the app writes its tokens to (spec C-8, A-4) |

## Chart values

`charts/hevy-garmin-sync-helm/values.yaml`, with these keys:

| Value | Default | Does |
|---|---|---|
| `image.repository` | `zimmertr/hevy-garmin-sync` | The image |
| `image.tag` | the chart's `appVersion` | The release the chart was packaged with |
| `existingSecret` | empty | A Secret you made with `HEVY_API_KEY`, `GARMIN_TOKEN` and, for Hevy Trainer, `HEVY_SESSION`. Empty makes one from `secret` |
| `secret` | empty | Those keys, for the Secret the chart makes |
| `env` | empty | Every other variable, as name and value |
| `persistence.size` | `64Mi` | The data volume |
| `persistence.storageClassName` | empty, the cluster's default | Its storage class |
| `persistence.existingClaim` | empty | A claim you made instead of a new one |
| `resources`, `nodeSelector`, `tolerations` | empty | As usual for a pod |
| `podSecurityContext` | uid and gid 1000, `fsGroup` 1000, non-root | Makes the volume writable by the image's user |
| `securityContext` | no privilege escalation, all capabilities dropped | The container's |
