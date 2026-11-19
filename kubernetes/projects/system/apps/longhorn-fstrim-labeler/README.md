# Longhorn Fstrim Labeler

This bundle labels every bound filesystem PVC backed by the
driver.longhorn.io CSI driver for the daily Longhorn filesystem trim
RecurringJob unless the PVC has home-lab.io/longhorn-fstrim: disabled.
It discovers the backing PV, so longhorn, longhorn-workers,
longhorn-control-plane, static Longhorn bindings and future StorageClass names
receive the same coverage. The CSI volume handle identifies the matching
Longhorn Volume custom resource, even when its name differs from the PV name.

Unbound PVCs are reconsidered on the next hourly run after binding. Raw block
volumes have no filesystem to trim and are skipped. NFS and other CSI drivers
are excluded; discard on a NAS filesystem belongs on its storage server.
PV access is read-only (get); label permissions remain limited to PVCs and
Longhorn volumes.

For disabled PVCs, the labeler removes filesystem-trim labels from both the PVC
and the matching Longhorn `Volume`. Use this for disposable or latency-sensitive
RWX cache volumes where Longhorn remount requests can generate recurring
`FailedMount` events without improving recoverability.

The CronJob runs hourly so existing PVCs and PVCs
created later by Helm charts or StatefulSet `volumeClaimTemplates` receive the
same labels without hand-editing generated claims.

The hourly CronJob requests `10m` CPU and `32Mi` memory and is capped at `250m`
CPU and `128Mi` memory. Finished Jobs have a 24-hour TTL so a failed run remains
available for alerting and diagnosis but does not accumulate indefinitely.
