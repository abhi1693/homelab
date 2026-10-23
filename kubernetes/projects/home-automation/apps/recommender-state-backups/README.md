# recommender-state-backups

The workload inventory classifies this prerequisite as a `component` of
[`cluster-ops`](../cluster-ops/catalog.yaml). Its retained claim, helper
configuration, and storage acceptance Job are part of that application.

This permanent Fleet prerequisite validates a retained NFS destination under the
explicit mapped NAS owner/group policy before its dependent application stops. It owns only one 16Gi retained PVC
`recommender-state-backup-nfs`, the immutable shared helper ConfigMap, a normal
post-install/post-upgrade storage acceptance Job and its deny-ingress/egress
NetworkPolicy. `helm.waitForJobs: true` holds readiness until the Job succeeds.
The Job has no source PVC, app credentials, ServiceAccount token, registry
imagePullSecret or network operation. It uses the independently public pinned
Chainguard Python interpreter directly, with UID/GID 65532, all capabilities
dropped and a read-only root filesystem.

The helper script bytes/hash exactly match the [canonical media helper](../../../entertainment/apps/media-state-backups/README.md).
All four profiles are finalized before the first media rollout; these later
namespace-local phases do not modify the media helper/hash or restart media apps.

## Normal bootstrap and ownership

This bundle uses `defaultNamespace: cluster-ops` and `createNamespace: true`. Fleet
v0.16.2's normal Helm install creates a missing bare target namespace with only
its name label. Helm4.2.2 does not attach Helm release ownership to that bootstrap
Namespace or include it in the release's rendered resources, and an existing
namespace is not patched. The dependent existing app bundle retains its exact
Namespace manifest, project/PSA labels and registry-SopsSecret ownership, then
applies them normally after this prerequisite becomes ready. There is no
namespace-owner transfer, duplicate Namespace manifest, namespaceLabels or
namespaceAnnotations, dependency cycle, temporary bootstrap commit, or manual
namespace operation. Keep that ownership layout unchanged. Source references:
[Fleet v0.16.2 install](https://github.com/rancher/fleet/blob/v0.16.2/internal/helmdeployer/install.go),
[Helm4.2.2 namespace creation](https://github.com/helm/helm/blob/v4.2.2/pkg/action/install.go).

## State and serial rollout gates

The source claim `k8s-recommendation-engine-shipyard-state` remains owned and mounted by the existing
single-replica Recreate app. The reviewed pre-upgrade state baseline was about 731,660,288 bytes.
This prerequisite never mounts or reads it. The later app's first init uses
4Gi bounded disk emptyDir and read-only source, requires a verified restore
point before any app writer starts, and masks its API token mount. The original
app main image/commands/policy/RBAC and source PVC remain unchanged until that
app's own separately reviewed release commit.

Before app rollout, record this prerequisite's current desired=applied IDs,
new bound PVC UID and the fresh exact-image storage acceptance Job success.
Do not substitute an older successful Job. The helper requests 0700 directories
and 0600 files and exercises file/directory fsync, atomic same-filesystem rename,
readback and cleanup. Those chmod requests do not prove persisted owner-only
permissions.
Failure leaves old app running and existing backups untouched. Hook deletion
uses before-hook-creation; TTL86400 retains success/failure evidence for one day.
Job deadline180s and helper120s sit inside Fleet300s. No backup trigger or
quiesce Job is used. App rollout/progress monitors allow2400s for the1800s
backup deadline plus normal startup.

Recommender's shipyard.db uses WAL and currently has no schema_migrations
ledger. Its Open() performs schema initialization, so never invoke its CLI just
to back up or inspect a live DB. The stopped-state helper stages DB+WAL on node
scratch, reconstructs SHM only there, uses SQLite Backup API and standalone
DELETE snapshot mode, and requires integrity/quick checks, exact sqlite_master
schema, user_version, application_id, explicit ledger presence/absence and
all table row counts to match isolated restored state. Source max1Gi, archive
max2Gi, scratch4Gi with512Mi reserve, retention3. A source-PVC-local backup
would not fit the baseline observed 272 MB free; the new destination is independent NFS.
Do not rename shipyard.db or the legacy source claim, reset proposal/cooldown
history, include volatile Git credentials/worktrees in backup, or invoke recovery.

## Persisted NAS receipt policy

Use the shared [storage policy](../../../entertainment/apps/media-state-backups/backup-storage-policy.json)
and [read-only receipt verifier](../../../entertainment/apps/media-state-backups/verify_backup_receipt.py);
the namespace-local ConfigMap carries unchanged canonical producer bytes. No
independent producer fork or policy/verifier copy is introduced.
The existing NAS maps claim-root, owner/point directories and receipt/archive
ownership to exact UID 977:GID 988. Protected directories may be 0700 or 0770,
files 0600 or 0660, with no world permissions, special bits, file execute bits,
symlinks or hardlinked protected files. Existing stricter modes remain valid.
The claim root's effective 0777 mode is recorded separately. This is a reviewed
NAS owner/group boundary, with `owner_only: false` and no encryption claim.

After a later real app backup init publishes a point, independently bind its
Pod UID, cohort, source PVC UID, destination PVC/PV UID/reference/class/driver and
exact node mount before invoking the canonical verifier. Supply the successful
init termination metadata and expected restore flag; do not infer expectations
from an unexpected receipt. The verifier reads only the bounded receipt and
archive file metadata, without rereading the archive, per-file manifest, keys or
DB rows. It compares the producer's verified hash/size/count/restore result;
it does not claim another full archive-integrity/restore run. This prerequisite's
acceptance Job validates destination operations only and creates no source-state
restore point.

The home-automation parent GitRepo explicitly discovers this folder in the same
change. `dependsOn` alone never registers a bundle. Repository metadata, docs and
tests are excluded by `.fleetignore`; run the storage contracts, generic tracked
project-registration regression and Renovate policy check after staging new
Fleet sources. The canonical helper remains `c24c14a3317c`; no application init,
image, credentials, Namespace resource or source PVC changes are part of this
storage prerequisite.
