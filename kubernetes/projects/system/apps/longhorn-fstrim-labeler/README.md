# Longhorn Fstrim Labeler

This bundle labels every PVC using the `longhorn` StorageClass for the daily
Longhorn filesystem trim RecurringJob unless the PVC has
`home-lab.io/longhorn-fstrim: disabled`. It also labels the matching Longhorn
`Volume` custom resource so existing bound volumes are immediately eligible for
the job.

For disabled PVCs, the labeler removes filesystem-trim labels from both the PVC
and the matching Longhorn `Volume`. Use this for disposable or latency-sensitive
RWX cache volumes where Longhorn remount requests can generate recurring
`FailedMount` events without improving recoverability.

The original one-time Job handled existing PVCs during the initial rollout and
was retired after completion. The CronJob runs hourly so existing PVCs and PVCs
created later by Helm charts or StatefulSet `volumeClaimTemplates` receive the
same labels without hand-editing generated claims.

The hourly CronJob requests `10m` CPU and `32Mi` memory and is capped at `250m`
CPU and `128Mi` memory.
