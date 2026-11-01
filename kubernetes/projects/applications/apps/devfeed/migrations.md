# DevFeed migration lifecycle

`migration-hook.yaml` is the single ongoing schema upgrade Job. Fleet invokes
Helm upgrades; Helm runs this `pre-upgrade` hook at weight -10 before replacing
application resources and waits for success. The immutable backend image must
match the application release. Migration failure blocks the upgrade.

`before-hook-creation,hook-succeeded` removes previous attempts before a retry and
cleans successful Jobs automatically. Failed hook Jobs remain for diagnosis.
Do not edit Helm release secrets or manually replay a running migration.

The hook uses existing configuration, database credentials and the `devfeed`
service account. A new environment must provision those dependencies, schema and
inbox credentials before installing the application. Historical production Job
manifests are not a supported initial-install procedure.

Hooks run before workload replacement. Drain incompatible background processes
through earlier Fleet revisions before migration; API readiness can briefly drop
until the matching replacement services start. Use an earlier compatibility
release when a migration cannot safely precede deployment.

Validate manifests with a server dry run, then verify the Helm hook's successful
last-run result, disappearance of the successful Job, live schema revision and
index validity, Fleet convergence and application readiness. Keep retained PVCs,
credentials and content through upgrades and cleanup.

## DevFeed JIT default

Before upgrading the schema, the hook verifies that both its login role and
database are `devfeed`, then commits:

```sql
ALTER ROLE devfeed IN DATABASE devfeed SET jit = off;
```

This uses the existing application role's permission to change its own defaults.
It leaves the server-wide default and every other role/database pair unchanged,
including Chimely. The hook closes its connection pool and verifies `SHOW jit`
on a new direct PostgreSQL connection before continuing with the schema upgrade.
The change targets JIT compilation overhead measured in DevFeed reports; it does
not change query results or disable ordinary planning and parallel execution.

Existing PostgreSQL backend sessions retain their previous default until they
disconnect. Session-mode PgBouncer reuses backend sessions, so a new application
connection alone does not guarantee activation. Allow normal backend replacement;
do not restart the shared PostgreSQL cluster or force a pooler rollout for this
setting. The interactive pooler also serves Chimely connections.

Verify the `jit=off` entry for the `devfeed` database and role in
`pg_db_role_setting`, fresh direct and pooled sessions, and subsequent report
durations/JIT counters. The hook's fresh direct-session check proves the saved
default; it does not prove every existing pooled backend has reconnected.

To roll back, replace the hook's `ALTER ROLE ... SET` statement with
`ALTER ROLE devfeed IN DATABASE devfeed RESET jit` and change its fresh-session
check and success log to expect the server default (`on`). Commit and reconcile
through Fleet.
Removing the enforcement code alone does not clear the persisted role default.
Existing sessions again need to reconnect before inheriting the restored default.

## Maintenance gates

For schema or serving-policy changes, use separate reviewed Fleet revisions to
stop admissions, drain actual workers and dependencies, apply the matching
migration image, verify core APIs and analytics health, and resume only the
owned pause. Stopping the scheduler alone does not stop queue consumption.

Verify a completed PostgreSQL backup and healthy WAL archiving first. Reserve
publisher connection capacity separately from interactive traffic and inspect
fresh global connection headroom. Do not roll both poolers simultaneously.

Require valid indexes, fresh reports under the current serving policy, healthy
publisher demand and leases, matching image digests and Fleet desired/applied
revisions before restoring processing. Retire completed one-time backfill hooks
through Git. Preserve the upgraded schema and recover with compatible images;
an image-only downgrade can be incompatible and cannot restore deleted data.

## 0.1.5 direct analytics

Provision healthy persistent ClickHouse before this upgrade. The hook uses the
ingestion schema owner to run PostgreSQL 0038 then the packaged ClickHouse schema
upgrade, with the reader cutoff recorded before new producers start. Ordinary
processes receive separate bounded service credentials and cannot run DDL.

Both legacy projector Deployments and alerts are retired in this revision. Wait
for all 0.1.4 application and worker pods to terminate before introducing the finite
importer in a later Fleet revision. Worker grace periods allow 1,500-second jobs
plus cleanup; native worker entrypoints and probes change with the image.

The finite `devfeed-analytics-importer` is enabled only after the producer handoff
revision is ready and no 0.1.4 producer remains. It has one bounded replica, a
recreate strategy and durable ClickHouse checkpoints; it imports retained history
and current cards before retiring legacy PostgreSQL analytics and declaring ready.
Monitor `analytics_history_import_complete` and `analytics_direct_status` before
calling analytical reports ready. Do not downgrade binaries after retirement.

Pre-upgrade hooks cannot consume ConfigMaps first introduced by the same upgrade.
The hook declares its ClickHouse endpoint and query bounds inline; ingestion
credentials already exist from the prerequisite revision. Ordinary producers
use the shared application ConfigMap created after the schema hook succeeds.

Repeat upgrades first validate immutable ClickHouse history and the fixed reader
boundary using read-only queries. When both are already prepared, they do not
reacquire the finite importer's advisory lock. Pending schema or a missing boundary
still runs the full ordered upgrade; invalid history fails closed.

## 0.1.6 priority queues and current analytics

The 0.1.6 pins come from [Release run 40982447613](https://github.com/abhi1693/devfeed.tech/actions/runs/40982447613),
attempt 1, at source `eac590a8aa2cd4510b681dacc53033aa432049a5`. All twelve
published components passed ARM64 platform, source/version-label, GHCR/Harbor
manifest-byte and digest-parity, and signed-provenance checks. Every application
container and init container uses that verified cohort. The ongoing schema hook fails before migration when its installed release or
schema identity is wrong.

The initial cutover completed through separate Git/Fleet revisions. The 0.1.5
image cohort and schema hook stayed in place while publishers, APIs, analytics
and ordinary workers drained. Solver remained available for dependent jobs, then
stopped in a second revision. All live worker registrations and started,
intermediate, scheduled and deferred entries were absent before migration.

The verified 0.1.6 schema hook applied PostgreSQL 0039 and ClickHouse migrations
through 0004 before consumers resumed. A temporary cleanup hook removed exactly
two stale Redis list pointers only after matching their delivery UUIDs, due/finish
timestamps, attempt and absent leases to already-succeeded durable jobs. That
verification used a bounded read-only transaction through the DevFeed pooler.
The native transport migration then reported `ready=true`, `applied=true` and
`complete=true`, moving all **805 queued deliveries** into the new queues.

The successful proof preserved every queued identity, serialized payload, retry
field, retained metadata and absolute expiry. It also preserved all **29 historical
failed-delivery records**, including their members and scores. Recorded proof:

| Evidence | Value |
| --- | --- |
| Queued identities SHA-256 | `b6cc7439376034d47c5f2c867589faaefc5839ab6f17c830341193d2bac28c8b` |
| Payload/retry SHA-256 | `8acef6c56f4b46e8d250552a1344ae80a22a19ba5c93dc30e562b8c455687e03` |
| Absolute expiry preserved | `true` |
| Failed history preserved | `29` |
| Already-completed stale pointers removed | `2` |

Both one-time Job manifests, Kustomization entries and temporary transport-test
fixtures are retired after this proof. Subsequent Fleet upgrades do not replay
that offline cleanup or queue migration against active workers. Completed Job
logs remain subject to their original one-hour TTL; retirement requires no manual
cluster deletion. Keep the ongoing schema hook, worker lifecycle, credentials and
network-boundary contracts.

All three priority pools receive notification delivery credentials and Codex
trust/configuration; Images and solver credentials stay isolated. Current pipeline
and audience reconciliation continue after the finite import, with the analytics
process using direct PostgreSQL for its session advisory coordination. Feed/topic
panels may show Preparing while bounded metadata repair finishes. Neither repair
nor rollback reconstructs lost historical observations.

Rollback is not an image-only operation: old binaries cannot consume the new
queues and may reject schema 0039. Keep processing stopped and recover with a
compatible image or a separately reviewed reverse routing/schema procedure.
Retain PVCs, credentials, checkpoints and migration evidence throughout recovery.

## 0.1.7 current-analytics fairness and recovery

The verified [Release run 41022549592](https://github.com/abhi1693/devfeed.tech/actions/runs/41022549592),
attempt 1, publishes source [9bbc6858](https://github.com/abhi1693/devfeed.tech/commit/9bbc6858cd9e03ef3fbd6ef499816bd851276f98).
This compatible image update retains PostgreSQL 0039 and ClickHouse 0004 and uses
the normal schema hook and rolling lifecycle, without replaying queue migration.

Publication admission waits asynchronously for at most ten seconds; source reads
retain five-second deadlines and each repair page has a twenty-second deadline.
A busy card refresh preserves valid queue progress and does not acknowledge an
unfinished card cycle. The reconciler alone publishes canonical cards; producers
acknowledge event delivery within the publication fence. RQ shutdown allows a
bounded drain and inference persistence retries never repeat a paid model call.

Bounded checkpointed recovery rebuilds facts retained in the sixteen PostgreSQL
sources, with original event times and restart-safe pending-page acknowledgement.
Preserve those records until recovery completes. Deleted records and overwritten
historical attempts cannot be reconstructed. Existing import checkpoints, policy,
reader cutoff, credentials, queues and worker reservations remain unchanged.

After Fleet convergence, verify two advancing complete card/queue cycles, all
sixteen source acknowledgements, nonzero matching publication counts and useful
background completions. Capture an empty canonical-card insert buffer after old
producers exit and require complete card source coverage newer than that barrier.
Pod readiness alone does not establish analytical correctness.

## 0.1.8 queue freshness, card recovery and reader startup

The verified [Release run 41063918969](https://github.com/abhi1693/devfeed.tech/actions/runs/41063918969),
attempt 1, publishes source [7439405b](https://github.com/abhi1693/devfeed.tech/commit/7439405bb165430a5809bfcfad86af45596b5f7a).
All twelve ARM64 images passed registry-cache byte/digest parity, source/version
labels and signed provenance checks. This compatible update retains PostgreSQL
0039 and ClickHouse 0004 and uses the normal schema hook and rolling lifecycle.
It does not replay the completed queue migration or change worker reservations.

Queue snapshots finish a bounded priority page before slower repair work. Card
recovery orders by the table's UUID primary key instead of sorting its text
projection before limiting each page. Ordinary reader feeds defer the Columns
workspace until it is needed.

Preserve existing history checkpoints, policy, reader cutoff, queues, credentials
and PVCs. After Fleet convergence, verify two advancing complete queue/card cycles,
all sixteen source acknowledgements, matching nonzero publication totals and
useful background completions. Capture an empty canonical-card insert buffer
after old producers exit and require complete source coverage newer than that
barrier. Readiness alone does not prove report freshness or correct recovery.
