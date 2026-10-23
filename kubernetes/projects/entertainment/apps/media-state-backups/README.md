# Media pre-start restore-point contract

The workload inventory classifies this prerequisite as shared `support` for
`media-stack`: its retained claims, helper configuration, and storage acceptance
Job support the qBittorrent controller and Ryokan without an independent service.

This design replaces the older separate quiesce/backup-Job proposal. It does
not add scale commits or a backup trigger. The shared stdlib helper and both retained backup claims are owned by the
`media-state-backups` prerequisite Fleet bundle. Both application bundles wait
for this prerequisite. Its normal post-install/post-upgrade storage-validation
Job runs as568 and65532 on their separate new claims, without source volumes,
Secret mounts, API tokens or network operations. `waitForJobs: true` prevents a
failed acceptance Job from making the prerequisite ready. Each
single-replica Deployment remains `Recreate`. Its **first** init backs up only
its own stopped state before application startup. For Ryokan this is before
`sync-qbittorrent-credentials`, which writes SQL/schema/config, and before both
Ryokan and its import-reconciler. Do not change these workloads to RollingUpdate,
add independent writers, or force-delete an unreachable old pod: Recreate alone
cannot fence a still-running writer after node/network failure. Recover/fence the
old writer before allowing replacement startup. The two restore points are
independent; no cross-pod global transaction is needed for these states.

The controller's normal stop-downloads-on-shutdown behavior is preserved. A
normal upgrade can interrupt downloads until the replacement reconciles policy.
Backing up state is not a reason to disable that policy. Paused replicas stay
zero and produce no backup activity.

## Release cohort regression gate

The dynamic `tests/test_backup_cohort_policy.py` requires both complete qBit
image references to match. Ryokan's first-init `--cohort` label includes its
actual core and qBit reconciler versions. The controller owns only qBit state,
so its own version must match while an optional strict-semver historical
`-ryokan-X.Y.Z` context remains unchanged during a Ryokan-only upgrade. Prefer
`qbit-<actual version>` for future controller cohorts; these tests do not rewrite
existing labels or require an unrelated controller rollout.
Recommender clone/main references must match; its and Rack's backup
labels track the actual app version once their phased backup init is installed.
Before that migration, missing backup init is accepted only for the exact unchanged
legacy references: both Recommender consumers at
`registry.home/ghcr.io/abhi1693/k8s-recommendation-engine:0.3.5` and Rack at
`registry.home/ghcr.io/abhi1693/rack-ops:0.1.3`. Any tag, registry or digest change
requires the first backup init, immutable writer pin and matching cohort together.
The later per-app migration tests always require that first init thereafter.
Keep related image pins and cohort labels in the same Git change. The assertions
derive versions from the manifests and accept future coherent releases.

The four writer packages retain branch automerge with a scoped `ignoreTests:
false` rule. Infrastructure regressions runs on Renovate branch pushes, before
merge, in addition to master and PR validation. An image-only update that leaves
a stale label fails this gate; repair the update rather than bypassing checks.
See the [Renovate workflow](../../../applications/apps/renovate/README.md#restore-point-writer-branch-checks).
No additional backup, helper change, forced rollout or temporary policy is added.

## Scope and storage

* Controller: the complete regular-file JSON state tree on its existing NFS
  state claim, including torrent-health and usage corrections. Cooling JSON may
  be absent. Missing required existing state blocks startup rather than silently
  initializing an empty controller.
* Ryokan: the SQLite database including committed WAL transactions, the 32-byte
  `.ryokan-key`, all other regular config/cache/artwork/import-reconciler files
  under `/data`. This preserves receipts and current owner/auth configuration.
  Actual external `RYOKAN_ENCRYPTION_KEY` is currently unset, so the file key is
  authoritative. Introducing an external key requires a separately verified,
  retained key restore procedure; do not silently assume this file remains it.
* Existing `/data/backups` and the specifically identified historical
  `ryokan.db.pre-jellyfin-key-20260812T165425Z.bak`, three named historical
  Shippuden snapshots and two named `recovery/naruto-shippuden-final-20260817T165000Z`
  snapshots (explicit allowlist in the helper) are left in place and excluded
  from the new archive. Pending auth-reset/restore markers, unexpected databases,
  incomplete temp files, symlinks or hardlinks fail closed for review.
* `/downloads` and `/media/anime` payload PVCs remain unchanged and are not copied
  into these state archives. The existing 15-minute qBittorrent **core** catalog
  backup is independent and unchanged; these init containers do not replace it.
* Use separate retained `nfs-shared-retain` claims: controller1Gi and Ryokan64Gi.
  The helper requests 0700 app/point directories and 0600 archive/receipt files.
  The existing NAS maps their effective ownership to UID 977:GID 988 and currently
  reports 0770 directories / 0660 files. This is the reviewed NAS owner/group boundary,
  with no world access on protected paths; it is not an owner-only or encryption
  claim. Stricter 0700/0600 modes are accepted without changing them. Keeping claims
  separate avoids fsGroup568/65532 ownership interference and cross-app pruning.
  NFS CSI currently has `ReadWriteOnceWithFSType`, and these RWX roots are created
  0777; the non-root helper must be able to create/chmod its protected child.
  NFS ownership mapping may differ from container UID; do not chown source data.
  NFS transport/server trust is the existing NAS boundary, not new encryption.

Ryokan backup runs as UID/GID568 with existing fsGroup/supplementalGroup568 and
can read the current568:568 mode0660 key. Controller uses65532. Source is mounted
**read-only**. The helper has no Secret/envFrom, API calls or network dependency.
Controller still needs its normal ServiceAccount token in the main container;
the backup init masks only its own token mount with a read-only empty directory.
All capabilities are dropped and root filesystem is read-only.

## Consistency, space and failure gates

The helper never opens live source SQLite for writes and never uses
`immutable=1` (which can silently ignore WAL). It copies the quiescent DB **and
WAL together** to bounded node scratch, reconstructs SHM only there, runs SQLite
Online Backup API, and makes the snapshot standalone with DELETE journal mode.
This handles a missing read-only source SHM without changing source. Full
`integrity_check`, `quick_check`, exact sorted **TEXT** migration IDs, complete
schema hash and `user_version` must match through snapshot and restored DB.
Numeric native Ryokan backup migration metadata is insufficient for this schema.

Ryokan uses disk-backed emptyDir24Gi with an explicit24Gi ephemeral request and
limit. Max source8Gi, max archive10Gi, 512Mi scratch reserve, two-times-source
free-space guard. The archive is streamed directly to NFS, so the source PVC
needs no backup workspace. Controller uses256Mi scratch, max64Mi state, max128Mi
archive,32Mi scratch reserve. Both also require destination headroom1Gi plus
source bytes and32Mi archive overhead. Requests remain part of pod scheduling;
recheck node ephemeral capacity and pressure before promotion. Current rpi4
read-only measurement:331,963,785,216bytes free, sourceDB3,430,551,552bytes,
sourcePVC8Gi, source free2,608,005,120bytes. These are baseline observations,
not permanent capacity guarantees. Maximum duration1800s and bounded file counts,
paths, JSON/manifest sizes, archive bytes and retention apply. Deployment progress
and Fleet Helm timeouts are2400s to cover the1800s backup budget plus existing
credential sync and normal startup probes. Serial rollout monitors must allow
this full budget rather than apply a shorter default. A stalled NFS
kernel I/O can hold the init longer despite a process deadline; it still cannot
start app writers. Do not bypass or ignore a failed init.

Each attempt streams into its own private `.partial-*` directory on NFS. It
fsyncs the tar, reads it back, validates every member/hash, safely restores all
files into separate scratch, and verifies DB/key/JSON again. Then it writes a
safe receipt, fsyncs the directory and atomically renames the entire directory
to `point-<UTC>-<randomID>`. Thus a completed point contains both tar and receipt.
NFS must support the helper's requested create/chmod operations, file fsync,
directory fsync and same-filesystem rename; any error blocks startup. The
prerequisite acceptance Job exercises those operations before Fleet may stop a
healthy old application, and each normal init checks the full write/restore path.
Persisted NAS permissions are verified separately against the explicit mapped
owner/group policy below; a successful chmod request is not proof of owner-only
effective permissions.

Three verified completed points per app are retained. A new point must fully
verify before pruning; only correctly named, owned, checksum-valid points are
eligible. Unknown files and abandoned partial directories are preserved for
review, not blindly deleted. Damaged prior completed receipts/archives block
startup rather than hiding backup corruption. NFS claim size is a Kubernetes
request, not a NAS quota; bounded count/bytes and actual free-space checks are
still necessary. The NAS backup dataset itself needs normal independent
protection; a retained PVC alone is not an offsite backup.

Receipts/logs expose only operation metadata, counts, archive/schema hashes and
booleans. File names, per-file hashes, migration ID values and original file
mode/UID/GID metadata live only inside the protected archive manifest, never logs.
`expected_source_pvc_uid` records the reviewed baseline expectation, not an API
attestation: the init has no PVC read permission. Root must independently match
live source claim UIDs before/after rollout; replacing a source claim requires
reviewing this expectation. No owner credentials or new keys are created.

## Rollout and restoration gates

Before promotion: verify the independently public immutable Chainguard Python index/ARM64
child/config against `public-helper-image.json`; compare live PVC UIDs, key mode,
writer mounts, encryption-key mode and node capacity against baseline; run the
helper/manifest tests and API-server dry runs for all changed resources; render
the prerequisite and both application Fleet bundles, including shared immutable
script references/dependencies. Record the prerequisite current desired=applied,
new claim UIDs and successful fresh acceptance Job (exact helper image) before
app rollout; for later prerequisite revisions, verify the new revision rather
than relying on an older successful Job. The Job timeout is180s (each helper120s),
backoffLimit1, and its Fleet timeout300s. `before-hook-creation` replaces an old
hook on the next normal upgrade, while TTL86400 retains current small success
or failure evidence for one day. It creates only disposable synthetic probes,
then cleans only its own uniquely named test directories. It never backs up,
prunes archives, reads source state or creates credentials. A NetworkPolicy
selects only validation pods and declares no ingress/egress; the code itself
makes no network request. Review overlapping policy allowances normally.
The helper uses only Python stdlib and runs via `/usr/bin/python` in the
independent public Chainguard minimal runtime. It is not coupled to the qBit app
release. Registry auth, app-owned imagePullSecrets, shells and installers are
not needed for prerequisite Jobs. The pinned current candidate is Python3.15.0,
SQLite3.54.1 and OpenSSL4.0.3; helper code supports Python>=3.12. The public `latest`
channel is resolved to an immutable digest; never deploy a floating tag. Verify
both native architectures with strict HIGH/CRITICAL including unfixed and
all-severity secret scans, nonzero OS inventory, SBOM and upstream signature
identity before changing the pin. See [Chainguard Python](https://images.chainguard.dev/directory/image/python/overview)
and its [exact public verification policy](https://support.chainguard.dev/hc/en-us/articles/53833609818779-Verify-Chainguard-image-signatures-with-cosign).
The final canonical helper already includes controller, Ryokan, Recommender and
Rack profiles. Later namespace-local prerequisites copy exactly these bytes/hash;
adding the other app phases must not change the media ConfigMap/init revision.
Source, tests, immutable ConfigMap content/hash and both pod references must
change together. Existing infrastructure regression CI watches both app trees.

CohortA changes qBit controller and Ryokan import-reconciler to the same verified
qBit0.2.13 index, adding these backups in the same desired-state commit. Keep
Ryokan core1.9.12 and qBittorrent core pins unchanged. Wait for both init
receipts/restore verification, normal credential sync, both main health probes,
Fleet desired=applied and public/media behavior. Later CohortB changes only
Ryokan core1.9.13, retaining the qBit pins and updating the cohort identifier;
its normal Recreate startup produces a new pre-migration restore point.
No background backup Job, direct exec write or temporary scale commit is required.

On failure: retain backups and source PVCs; inspect the safe termination reason.
Do not bypass init, restore automatically, downgrade a migrated schema, reset
owner auth or overwrite live WAL. A verified archive is a rollback prerequisite,
not proof every older binary can consume a newer schema. An offline restore is
a separately reviewed operator/GitOps recovery operation: all relevant writers
must be stopped/fenced, the selected archive/receipt hash verified, complete
manifest safely restored into an isolated directory, then SQLite integrity,
exact schema/TEXT migration set and32-byte key verified. Restore the whole
matching state/key pair and original reviewed file modes/UID/GIDs before restart;
never merge an old DB with a current WAL/SHM, overwrite active state, or activate
reset-auth/restore sentinels. Keep the pre-restore state separately. The helper's
`restore_verify` function safely exercises the isolated restore contract, but
intentionally has no command to apply a restore onto live PVCs.

Local regression command:

```sh
python3 -m unittest discover -s kubernetes/projects/entertainment/apps/media-state-backups/tests -v
```

The Recommender/Rack profiles are shared implementation capabilities; their
namespace-local prerequisites and app init containers land in separate serial
app phases. Those phases must not alter either media app image or this finalized
helper content hash. They preserve app Namespace and registry-SopsSecret owners.

The helper's Docker metadata is explicitly disabled for automatic updates in
Renovate's final package rule. The rolling `latest` channel is consumed only by
immutable digest after signature, both-platform scan/inventory and helper-profile
review; changing a tag alone cannot establish compatibility for retained state.

The prerequisite is selected explicitly by the entertainment project GitRepo.
A Fleet dependency name alone does not discover a new directory; add each new
namespace-local prerequisite to its parent GitRepo path list in the same change.
The contract tests enforce this for all three backup bundles as they are added.

## Persisted receipt metadata policy

[backup-storage-policy.json](backup-storage-policy.json) records the existing NAS
boundary for all four helper profiles: exact UID 977:GID 988 on the claim root,
owner directory, completed-point directory, receipt and archive. Protected
directories may be 0700 or 0770; receipt/archive files may be 0600 or 0660. World
access, special bits, executable files, hardlinked files and symlinks are rejected.
The claim root's effective 0777 mode is recorded separately, not treated as a
protected owner/point directory. `owner_only: false` describes the agreed trust
boundary even when stricter protected modes are observed. NAS administrators and
the mapped NAS owner/group remain trusted; no encryption or isolated-container
identity claim follows from these mode bits.

The Linux stdlib utility [verify_backup_receipt.py](verify_backup_receipt.py)
performs read-only persisted metadata verification. Its caller first verifies
the exact live Pod, bound destination PVC/PV reference/UID/storage class/CSI driver,
source PVC UID and node mount. The request must supply that explicit mount, init
reader UID/GID, owner, completed-point name, Pod UID, source claim name/UID, cohort,
`restored_verified: true`, and the successful init termination fields: status,
point, archive SHA256, byte count and file count. Pass the request through
`--request-json` and the reviewed policy through `--policy` or `--policy-json`.
No values should be inferred from an unexpected receipt to make it pass.

Every mount component and protected child is opened without following symlinks.
A privileged host invocation drops to the requested init UID/GID before reading
the protected directories. An already unprivileged reader must have no
supplementary group outside the requested GID. It reads only a bounded receipt
(maximum 8192 bytes),
rejects duplicate/nonfinite JSON, binds all expected identities/counts/hash and
restore flag, checks exact completed-point contents and stable file/directory
stats, and inspects archive size/type/link count/mode through an `O_PATH` handle.
It never opens the archive for body reads, rehashes its 3.6 GB payload, reads its
per-file manifest/key/database rows, chmods, restores, or calls a cluster API.
The producer already read back the archive, checked its hash and restored it
fully before publishing; this verifier compares the retained receipt with that
trusted producer result. A separate full-integrity/restore operation still needs
an actual archive read. Inputs supplied by the caller are expectations, not an
independent API attestation. Outputs expose safe metadata/aggregates only.

The policy/verifier/tests are excluded from Fleet resources by `.fleetignore`.
They do not alter the canonical backup helper, its immutable ConfigMap or pod
references, so metadata verification does not rerun a backup or restart an app.
