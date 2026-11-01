# DevFeed ClickHouse recovery evidence

## Meaning

Two unreadable ClickHouse parts interrupted DevFeed administration analytics on
2026-10-29. Recovery used an isolated PostgreSQL point-in-time restore, a fenced
current snapshot, native salvage, and append into the existing ClickHouse tables.
Offline inspection confirmed zero-filled compressed blocks in the damaged data.
Node power loss is a possible cause, inferred from the incident history rather
than established by the damaged-block checks.

This runbook records the evidence that must remain after temporary recovery jobs
and the restore clone are retired. Recovery implementations remain in Git history
under `kubernetes/projects/database/apps/devfeed-clickhouse-recovery` and
`postgresql-devfeed-recovery`; they are not normal application components.

## Impact

Original table UUIDs and incoming writes must remain intact. Staging, salvage
seeds, journals and detached damaged files are retained for further investigation.
Do not drop, truncate, exchange or rename these tables, delete detached parts, or
remove the production ClickHouse volume as part of infrastructure cleanup.

## Diagnosis

Run the following read-only SQL using the normal operator connection. Expected
original/staging identities are:

| Table in `devfeed` | UUID |
| --- | --- |
| `analytics_pipeline_events` | `16112dea-83b3-451c-bc42-8e995b305407` |
| `analytics_inference_events` | `d9a244ca-a4c3-4e2c-8f30-2a61fbe4bbdf` |
| `analytics_pipeline_events_recovery_20261029` | `1f866630-e21f-45c0-beed-9eee9dfffbe7` |
| `analytics_inference_events_recovery_20261029` | `a8c1d451-2ac4-4509-b236-3ea009f9d180` |

```sql
SELECT name, uuid FROM system.tables
WHERE database='devfeed' AND name IN
('analytics_pipeline_events','analytics_inference_events',
 'analytics_pipeline_events_recovery_20261029',
 'analytics_inference_events_recovery_20261029') ORDER BY name;
SELECT source,generation,state,revision,rows,pipeline_uuid,inference_uuid,source_fingerprint
FROM devfeed.analytics_recovery_replay_20261029 FINAL ORDER BY source;
SELECT source,state,current_generation,current_revision,expected_rows,scanned,
       inserted,skipped,checksum,seed_table,seed_uuid,raw_sha256,native_sha256
FROM devfeed.analytics_recovery_salvage_20261029 FINAL ORDER BY source;
SELECT table,name FROM system.parts WHERE database='devfeed' AND active
AND ((table='analytics_pipeline_events' AND name='all_6470_10957_3572')
  OR (table='analytics_inference_events' AND name='202610_1857_6637_4701'));
SELECT table,name FROM system.detached_parts WHERE database='devfeed'
AND ((table='analytics_pipeline_events' AND name='all_6470_10957_3572')
  OR (table='analytics_inference_events' AND name='202610_1857_6637_4701'));
```

Require both replay rows `complete`, the damaged-active query empty and exactly
two detached rows. The PITR generation is
`4d1c3e11-54e5-4d22-aa40-181a420aef37`, revision `1`, rows `2037388`, fingerprint
`d884c0e79021f288995f61d198a5faf241f9a0ba1e2f5277c12df78992427a6c`.
The current generation is `b46d1da8-0cf5-4ef0-923d-5d3f2b5af7bf`, revision
`51772602`, rows `1481959`, fingerprint
`ff8e003a1cde7212af25ad751b5b2a21b267cd9b374d05a54b2b9e653fd41234`.
Current completion was acknowledged at 13:39 UTC after full-column reads and
64 conflict-validation buckets; no second business-data scan was needed.

Append repair v3 completed successfully at **2026-10-29 14:17:21 UTC**; the
Kubernetes Job reported `Complete` at 14:17:23 UTC, with exit code 0 and no
restarts. Both tables passed all 64 canonical identity/revision/payload buckets.
Full-column reads of the serving tables then passed with 10,831,104 physical
pipeline rows and 1,669,817 physical inference rows. These are completion-time
physical counts, including raw versions; ongoing writes and merges change them.
Original UUIDs were rechecked, and both exact damaged parts were retained in
`detached/` after successful coverage verification.

A lightweight `system.tables.engine_full` check after append completion confirmed
`fsync_after_insert=1`, `fsync_part_directory=1` and
`min_rows_to_fsync_after_merge=1` on **all four** original/staging tables listed
above, with the same pinned UUIDs. Inspect those settings without a data scan:

```sql
SELECT name,uuid,engine_full FROM system.tables WHERE database='devfeed'
AND name IN ('analytics_pipeline_events','analytics_inference_events',
 'analytics_pipeline_events_recovery_20261029',
 'analytics_inference_events_recovery_20261029') ORDER BY name;
```

Post-repair live diagnostics invoked the actual unmapped report builders and
all 12 chart serializers. All seven groups returned fresh snapshots within the
normal 12-second limits, without SQL, codec, memory or deadline errors:

| Report group | Sequential diagnostic latency |
| --- | --- |
| operations | 563 ms |
| publishing | 94 ms |
| audience | 74 ms |
| processing | 1405 ms |
| inference | 1560 ms |
| coverage | 278 ms |
| queues | 465 ms |

A final cold parallel batch also passed **all 12 charts on the first attempt**,
with zero retries or errors, in **5582 ms total** (slowest inference chart
5581 ms). It exercised the real unmapped tables through the shared API/runtime
section path, normal 12-second deadlines, two query slots and coalescing, with
Redis disabled for that diagnostic. This proves live report calculations,
serialization and cold concurrent scheduling; it does not certify browser
rendering or session authentication.

Final metadata checks found both damaged parts inactive and detached, unchanged
original/staging UUIDs, and damaged `data.bin` SHA-256 values matching their
pre-repair values. ClickHouse remained Ready with no restarts or OOM events. A final live rerun
after capture retirement and diagnostic-log repair passed all seven report
groups and all 12 serializers again, with fresh snapshots and a maximum group
latency of 1706 ms. The 103-second post-repair observation found no new errors,
including codes 432 and 497, and all three original damaged-file SHA-256 values
were preserved. All cleanup publication gates therefore passed.

Salvage completed at 13:41 UTC against that same current generation/revision:

| Source | Expected/scanned | Inserted / skipped | Checksum | Retained seed UUID |
| --- | --- | --- | --- | --- |
| pipeline | 40770 | 0 / 40770 | `7237446473178818125` | `5def92bb-ee31-4636-850f-87bd8b6f2cd7` |
| inference | 19994 | 2389 / 17605 | `5861218571219806639` | `455daa8a-d856-42b6-ac04-0511b9e44ec5` |

Retain all `analytics_pipeline_salvage_20261029_*` and
`analytics_inference_salvage_20261029_*` tables, both staging tables,
`analytics_recovery_replay_20261029`, `analytics_current_snapshot_20261029`, and
`analytics_recovery_salvage_20261029`. The salvage journal records exact seed
names and raw/native SHA-256 proofs; never substitute a similarly named table.

Separately, repeated diagnostic-log merge failures confirmed corruption in
`system.text_log`, UUID `824f92d3-b0e4-4d40-815f-bb320446f336`, part
`202610_1219_1239_4` (34,427 rows, 1,628,398 bytes). Read-only physical inspection
recorded its `data.bin` SHA-256 as
`3764378d47d979070e0355b3287b573a77d513abe9122b5fef70051f4fad8a25`.
The Git-managed repair at `9164ce045` permits only detaching that exact part,
after UUID/engine/row/byte/state checks, and requires the same table identity,
zero active and one retained detached part afterward. The Job logged success at
**2026-10-29 14:34:33 UTC** and reached Kubernetes `Complete` at 14:34:36 UTC.
Independent native inspection confirmed that the retained file's actual SHA-256
matches the recorded inspection hash. All three damaged parts' hashes and table
UUIDs remained unchanged. A 103-second observation window after Job completion
found no new errors or codes 432/497; ClickHouse stayed Ready with zero restarts
or OOM events.

## Mitigation

Cleanup is two reviewed Git/Fleet changes, published only after append repair and
real reports pass. First run the guarded capture-retirement Job. It removes only
`analytics_pipeline_events_recovery_capture_20261029` (UUID
`60c5d95f-9271-43fc-9757-05d40a68a899`) and
`analytics_inference_events_recovery_capture_20261029` (UUID
`c5a1f06d-3df3-4d9a-a28f-7215697e934f`). The guard pins their definitions,
original/staging UUIDs, both exact replay and salvage proofs, and detached parts.
`DROP VIEW … SYNC` removes these external-`TO` insert triggers and leaves their
destination tables and rows intact. Verify both views absent before proceeding.

The guarded capture-retirement Job completed successfully on **2026-10-29
14:23:28 UTC**, exit code 0. Pipeline and inference trigger removals were logged
at 14:23:20.545 and 14:23:26.097 UTC respectively, followed by successful
original/staging identity, durable completion-evidence and retained-detached-part
rechecks. Both capture views are absent; duplicate capture writes have stopped.

Then remove the two recovery app directories, explicit database Fleet discovery
paths and temporary workload-catalog exclusions. Do not change namespaces or
production PostgreSQL/ClickHouse app manifests. Do not reintroduce old Job
manifests to retry cleanup: historical scripts can restart completed work.

The only restore cluster being removed is
`postgresql/postgresql-devfeed-recovery-20261028`, UID
`280eb613-5eb4-4c52-b787-1fa6ecabc24d`. Its two controller-owned Longhorn PVCs
have reclaim policy `Delete`, so normal Cluster garbage collection should release
exactly 36 GiB of provisioned volume capacity (replicated physical use differs):

| PVC in `postgresql` | Size | PVC UID / PV name suffix |
| --- | --- | --- |
| `postgresql-devfeed-recovery-20261028-1` | 32 GiB | `577ad138-e6a5-4017-91b2-bbd8ab41d41a` |
| `postgresql-devfeed-recovery-20261028-1-wal` | 4 GiB | `3d357c27-0fb3-4963-9c38-abef87096219` |

Both PV names are `pvc-` followed by the listed UID. Recheck ownerReferences and
UIDs before publishing cleanup. The clone had only an external archive read
source, with no `spec.backup`, plugins or replica writer; original R2 backups and
the `s3://home-lab-postgresql/` source prefix must remain. Its backup
`20261028T000001`/timeline 69 restore stopped before transaction 51105783 at
17:20:00.264720 UTC on October 28; last commit was 17:19:59.512104 UTC.

The generated `devfeed/devfeed-analytics-recovery` Secret, UID
`953c4678-6e1b-4a9b-ac80-c5477d9e840e`, is controller-owned by
`devfeed/devfeed-analytics-recovery-secrets` SopsSecret, UID
`a0a13bee-7cdb-4089-8fee-697802a9e2a2`. The live owner UID matches and neither
resource has finalizers. Removing the app removes that SopsSecret; normal garbage
collection must also remove its generated clone-DSN Secret. Do not retain a clone
credential after removing the clone.

## Verification

Confirm Fleet has applied the cleanup revision and both recovery bundles are
removed. Read-only checks must find no clone cluster, its pods or either exact
PVC/PV. If ownership/finalizers prevent garbage collection, investigate; do not
force-remove protection or delete similarly named resources.

```sh
kubectl --context local -n postgresql get clusters.postgresql.cnpg.io postgresql-devfeed-recovery-20261028
kubectl --context local -n postgresql get pods,pvc -l cnpg.io/cluster=postgresql-devfeed-recovery-20261028
kubectl --context local get pv pvc-577ad138-e6a5-4017-91b2-bbd8ab41d41a pvc-3d357c27-0fb3-4963-9c38-abef87096219
kubectl --context local -n devfeed get sopssecret devfeed-analytics-recovery-secrets
kubectl --context local -n devfeed get secret devfeed-analytics-recovery
kubectl --context local -n clickhouse get pvc clickhouse-data
kubectl --context local -n postgresql get clusters.postgresql.cnpg.io postgresql
```

The production ClickHouse PVC stays Bound at 50 GiB, UID
`a0f8703b-2333-4eaf-a91e-9e1111b7793b`, PV
`pvc-a0f8703b-2333-4eaf-a91e-9e1111b7793b`. Shared PostgreSQL stays healthy at
three instances. Repeat the SQL evidence checks, confirm both capture views are
absent, and check real administration reports again after infrastructure cleanup.

## Rollback

Retiring capture views does not undo recovered data. Their recorded definitions
can be reviewed from Git history if capture is needed again. Removing the clone
releases its disposable volumes; recreating it requires a fresh reviewed restore
and available archived backups. Do not reverse infrastructure cleanup by blindly
restoring every historical Job. Any deletion of retained SQL evidence or detached
data requires a separate decision after the incident is closed.

## References

- [ClickHouse materialized-view trigger and target behavior](https://clickhouse.com/blog/using-materialized-views-in-clickhouse)
- [CloudNativePG backup and recovery](https://cloudnative-pg.io/docs/1.30/appendixes/backup_barmanobjectstore/)

## Workflow audit

Temporary Wardn skills used for incident review (bundle SHA-256):

| Skill | Publisher / repository | Purpose | SHA-256 |
| --- | --- | --- | --- |
| `devops-troubleshooter` | `rmyndharis/antigravity-skills` | Incident workflow | `8678fd7e369a52bb302796a3e0e107c8a9716fc62c0e667802c59146d25de742` |
| `data-engineer` | `sickn33/agentic-awesome-skills` | Replay integrity | `ebfa6bc66ca89be957090681e5d7bc9e03cb947cdc3fa3a7b606e273e0a63f93` |
| `kubernetes-architect` | `rmyndharis/antigravity-skills` | GitOps pause safety | `31242e814a42cb7f6b66ad5bd3bdcaac76bab323d8ccdc028cbad1bb5e1c4b56` |
| `cc-skill-clickhouse-io` | `sickn33/agentic-awesome-skills` | Bounded ClickHouse metadata/I/O review | `36850c84e2cf2bde3d93c06f8d53091c43835fd843d4ad9dd32d66697a764170` |

The diagnostic-log review bundle scored 99/low risk; its exact temporary bundle
was removed after use.
