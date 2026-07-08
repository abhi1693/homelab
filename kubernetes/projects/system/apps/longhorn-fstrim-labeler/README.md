# Longhorn Fstrim Labeler

This bundle labels every PVC using the `longhorn` StorageClass for the daily
Longhorn filesystem trim RecurringJob. It also labels the matching Longhorn
`Volume` custom resource so existing bound volumes are immediately eligible for
the job.

The one-time Job handles existing PVCs when the bundle is first reconciled. The
CronJob runs hourly so PVCs created later by Helm charts or StatefulSet
`volumeClaimTemplates` receive the same labels without hand-editing generated
claims.
