# NetBox 4.7 pre-upgrade rollback point

This one-time Fleet Job is admitted only after the old NetBox web/housekeeping
workloads have been quiesced through Git and observed stopped. It takes a
read-only consistent PostgreSQL custom-format dump, validates its archive
listing, and publishes checksums and a receipt under the retained private NAS
claim `netbox-pre-upgrade-backup-nfs`. There is no recurring backup schedule.

The directory is `netbox-4.6.9-before-4.7.4-20261103`. Its files use NAS-mapped
owner/group `977:988`, directory mode `0770` and file mode `0660`. The database
dump is private but is not claimed to be encrypted at rest. The chart-generated
session/API-token configuration Secret is separately age-encrypted with the
repository's SOPS recipient before entering Git or the backup Job. Decrypt that
artifact only with the operator's existing age identity, never in a public log.
Production database and Valkey credentials remain in the existing SOPS bundles.

A receipt makes repeat execution verify the existing point instead of replacing
it. A partial directory is retained and causes a retry to stop. Completed Jobs
have no TTL to avoid Fleet repeatedly recreating a pruned Job. The completed
Job also keeps its original image digest: Kubernetes does not permit changing
its pod template. It is intentionally excluded from annotation-driven image
updates. A future backup requires a separately named Job and reviewed receipt
path; do not refresh this retained Job alongside the live PostgreSQL catalog.

Rollback across the NetBox schema boundary requires stopping the new workloads
through Git, restoring this dump and the matching configuration, and restoring
the 4.6.9 image/chart/plugin values. New writes after cutover need reconciliation;
never point 4.6.9 at the migrated database. Retain the original NAS media claim.
Any SQL restore must be represented as a separately reviewed Fleet operation.

The bound PVC volume name is pinned. Drift correction uses normal patching
(`force: false`) because force-replacing bound claims and completed Jobs would
try to remove Kubernetes-assigned immutable fields. The backup stays retained.
