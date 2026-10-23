# DevFeed 0.1.2: administration read-model cutover

Release 0.1.2 requires schema `0034` and two independent administration publishers.
The previous 0.1.1 applications reject this revision in readiness. This is an
explicit maintenance boundary, not a zero-downtime schema upgrade. Preserve
accounts, articles, processing history, sessions, storage, and the article-derived
topic proposal pause. Do not replay historical jobs or downgrade the schema.

The initial cutover includes a one-time pre-upgrade backfill hook. Its pool,
policies and encrypted URL must exist before that first attempt. Once the pipeline
is complete under its current serving policy, retire the hook through a separate
availability revision; report failures must not indefinitely block compatible core
APIs and durable publishers. All 27 fresh default reports remain mandatory before
owned queue resume. Use separate Git commits and verify Fleet desired/applied
equality for each completed stage. All cluster changes are reconciled by Fleet;
the commands below inspect state only.

## Before production changes

- Require the release PR and exact resulting `master` CI to pass before tagging.
- Require the tag CI, immutable image manifest, all twelve ARM64 source
  attestations, and GHCR/Harbor raw digest parity. Replace every runtime,
  init-container and migration image with that release's exact verified digest.
  An old digest combined with a new tag is not a release image.
- Verify a completed CNPG backup and healthy WAL archiving. An unrelated backup
  currently running is not proof that the most recent successful backup failed;
  inspect Backup objects and the successful backup's completion time.
- Record the current schema, valid indexes, workload replicas, queue deliveries,
  pooler clients/waits, and PostgreSQL connection headroom. Capture a read-only
  lifecycle sample for comparison after cutover. Do not log session credentials
  or private article evidence.
- Register maintenance expectations for readiness and admin availability while
  the schema changes and the initial ARM64 backfill runs. The 300,000-review
  synthetic x86 fixture measured roughly six seconds for the two standard
  review indexes and 391 seconds for backfill; production ARM64 timing is unproven.

## Connection reservation

The existing interactive pool remains two replicas with ten backend slots each.
The dedicated `postgresql-pooler-devfeed-read-model-rw` has two replicas with two
slots each. Per-database and per-user limits prevent either pool from expanding
past these budgets. The publishers use short-lived NullPool connections and one
calculation per process; Recreate deployments prevent publisher rollout surge.
They cannot reach the interactive pool through the authored NetworkPolicies.

The unchanged CNPG-generated Deployment strategy allows one extra pod during a
two-replica pooler rollout. The maximum DevFeed application-role demand is:

| Demand | Steady state | Simultaneous pooler rolls |
| --- | ---: | ---: |
| Interactive pooler | 20 | 30 |
| Read-model pooler | 4 | 6 |
| Direct migration | 1 | 1 |
| Total | 25 | 37 |
| Managed `devfeed` role limit | 40 | 40 |

The three remaining role slots cover diagnostics or recovery clients; they are
not another unbounded workload budget. Failover re-establishes sessions within
the same per-pooler limits rather than adding replicas on the new writer.
Account separately for CNPG pooler authentication connections, replication,
operator access, and other applications against PostgreSQL's global limit of
160. Role limits across unrelated apps are not all reserved simultaneously.
Recheck live global headroom before each phase rather than assuming one sample
guarantees future capacity.

The 2026-10-23 preflight observed 106 global connections, fifteen DevFeed-role
sessions, seventeen total pooler-authentication sessions (five in the existing
DevFeed pooler), three active queries and zero lock waiters. Indexes were valid.
With the existing pooler unchanged, filling twenty interactive slots, four
publisher slots and one direct migration slot, plus four new authentication
slots, would be `106 + (25 - 15) + 4 = 120` connections: forty global slots of
headroom in that sampled state. Unrelated demand can still change that result.

Simultaneous pooler rolls must not occur during this release. Expanding both
application and authentication pools to their simultaneous-roll ceilings could
instead reach `106 + (37 - 15) + (36 - 5) = 159` connections, leaving inadequate
global headroom. The application-role limit alone is not a global reservation.
Phase 1 changes existing parameters through CNPG reload and provisions the new
pool without changing PgBouncer images or existing Pod templates. Record the
existing pooler Pod UIDs and verify no replacement occurred. If an unrelated
pooler rollout is active, wait for it to finish and recheck actual demand and
authentication counts before proceeding. Keep pooler upgrades separate from
this release; any future pooler roll needs a fresh global capacity calculation.

## Phase 1: provision the reserved pool

Commit the database role/pooler changes, both namespaces' pooler NetworkPolicies,
and encrypted `devfeed-read-model-database` secret. Keep the 0.1.1 application
images and original migration hook. Do not add the new backfill hook or start
the publishers in this phase. The SOPS URL retains the existing login and changes
only the host; no new identity provider or management credentials are granted.

Verify the managed role limit is 40, both new pooler replicas are Ready on
different nodes, and the actual per-pooler limits match the budgets above.
Check both existing interactive instances too: `cl_waiting` must remain zero.
Confirm the encrypted-secret operator produced the required key without printing
its value.

```sh
kubectl -n postgresql get poolers.postgresql.cnpg.io
kubectl -n postgresql get pods -l cnpg.io/poolerName=postgresql-pooler-devfeed-read-model-rw -o wide
kubectl -n postgresql exec <pooler-pod> -c pgbouncer -- \
  psql -X -U pgbouncer -h /controller/run pgbouncer -c 'SHOW CONFIG;' -c 'SHOW POOLS;'
```

## Phase 2: quiesce old background writers

Through one Fleet revision, stop the scheduler, search indexer and admin API,
and wait for their processes to exit. Record the original replicas of all thirteen
worker Deployments, including the three article-analysis replicas. Keep the two
new publishers absent. Durable queued work can remain throughout maintenance.

Do not scale busy workers directly to zero. Existing article deliveries allow
1,500 seconds, but their old Pods allow only 300 seconds for termination. Solver
deliveries can also exceed the solver Pod's 180-second grace. Changing a Deployment
template cannot extend the grace of an already-running Pod. Observe executions
using raw Redis reads: RQ registry convenience getters can mutate job state.

Use a separately validated Fleet maintenance Job to own a bounded `rq:suspended`
pause and request normal warm shutdown once per exact old worker. RQ suspension
is database-wide and does not immediately stop a worker already blocked in a
dequeue. Require exact DevFeed worker/Pod ownership and no foreign active queues
before acquiring it; refuse any pre-existing pause. Never blindly repeat a warm
shutdown command: a second SIGINT can kill the running job.

Topic work can synchronously wait for a solver delivery. The maintenance Job must
therefore keep one solver consumer available during the drain. Use the deployed
0.1.1 image and schema, the existing solver restrictions, and a bounded solver-only
bridge that bypasses only this Job's owned pause. Prewarm the bridge, then hand
off only after the original solver finishes and exits; concurrent solver workers
can fail on the normal nonblocking provider lock. Replacements must acknowledge
suspension. Check pause ownership and remaining lifetime before each delivery.
Keep the bridge running until every old producer has finished, then drain solver
deliveries and prove the bridge process has exited. An empty queue at startup
does not establish that all producers have finished.

Require native ARM64 success and failure fixtures against the exact maintenance
script and old image before installing this Job. A publish-attempt ledger proves
at most one attempt, not guaranteed PubSub delivery. Ambiguous acknowledgement,
foreign ownership, a deadline or missing execution evidence must fail the gate;
retain the pause for diagnosis rather than retrying shutdown or claiming a drain.
Record intentional old-container warm-stop restarts separately from unexpected
restarts of the new release.

Only after all old executions and the bridge have exited and replacement workers
are suspended, use the next Fleet revision to set all thirteen workers to zero.
Verify every old worker process is gone before migration. The temporary old-image
maintenance Job must be finished before schema `0034`; it is not part of the new
release's running image cohort. Preserve the owned pause for the cutover and
verify its remaining lifetime before each phase.

Do not confuse orphan queue IDs with active work. Do not clean or requeue
unrelated work. Do not cancel a running migration or edit Helm release secrets.

## Phase 3: migrate, build the pipeline, and restore core availability

Commit the exact release image pins for all services and init containers, the
new publisher Deployments, and the backfill hook. Restore the admin API and
indexer replica counts, keeping all thirteen RQ worker Deployments and the
scheduler at zero. Preserve the recorded original fifteen worker replicas for
the later restore revision.

The immutable 0.1.1 and 0.1.2 RQ workers refresh Redis heartbeats while suspended,
but those pipelined heartbeats do not refresh their local health markers. Starting
them under the owned pause causes probe-driven restarts. Keep their normal
commands and probes unchanged: do not start paused RQ workers or require them
Ready as a prerequisite for clearing the pause. Backfill and both publishers run
direct database projection loops, and core APIs serve the completed projections;
these gates do not require an executing RQ delivery.

The initial Helm attempt runs `devfeed-migrate` at weight -10, then
`devfeed-read-model-backfill` at weight -5, before it replaces application
resources. The second hook refuses a missing reserved URL, drains the bounded
pipeline, verifies the serving policy matches this runtime and is complete,
then publishes and validates every default report group/range against the
current report policy. Sixteen report groups produce 27 default snapshots
because time-based groups include both seven- and thirty-day ranges. A failed
report cannot pass merely because another report succeeded. `backoffLimit: 0`
disables retries within this Job; Fleet may start a later Helm attempt, whose
`before-hook-creation` policy removes the previous Job. Preserve each original
hook result and logs rather than claiming every managed attempt succeeded.

The migration deadline remains 840 seconds. The initial hook is bounded to 1,800
seconds, with normal per-query timeouts and 100-row batches retained below the
120-second publisher lease. Fleet's 3,600-second Helm timeout accommodates both
sequential Jobs and active core pod readiness. These are operational failure
bounds, not measured production completion times. If a batch exceeds its lease,
the guard fails instead of publishing partial state. Inspect the retained Job
logs and actual resource/wait data before choosing any forward fix.

```sh
kubectl -n devfeed get jobs,pods
kubectl -n devfeed logs job/devfeed-migrate
kubectl -n devfeed logs job/devfeed-read-model-backfill
helm -n devfeed history devfeed
helm -n devfeed get hooks devfeed
```

Successful hook Jobs are deleted by Helm. Use recorded hook results and captured
logs rather than treating a missing Job as failure or success. A pipeline-complete
result and current serving policy can be verified even when later report seeding
fails; never describe that as full backfill or release success.

For availability recovery, require schema `0034`, valid indexes and durable proof
that the pipeline is complete under this runtime's current serving policy. Then
remove `read-model-backfill-hook.yaml` and its Kustomization entry. Keep the normal
migration hook and every Deployment's images, replica counts, commands and probes
unchanged. This lets compatible core APIs and both durable publishers deploy while
individual report failures are diagnosed and repaired independently.

A changed desired bundle is queued through normal Fleet reconciliation. The pinned
Fleet agent serializes reconciles for the same BundleDeployment and does not
cancel the active Helm call when a new desired generation arrives. Preserve actual
attempt and Pod outcomes; do not force updates, cancel hooks or alter Helm secrets.
Do not require all reports to complete before restoring public API availability.
Keep all RQ workers and the scheduler at zero throughout this stage.

## Phase 4: verify freshness and resume scheduling

Verify schema `0034`, valid indexes, matching active core runtime/init image IDs,
successful migration records, retained pipeline-completion proof, Fleet convergence,
all active core replicas Ready and no
new container restarts. All thirteen RQ worker Deployments and the scheduler must
still have zero desired replicas, with no remaining worker Pods, registered RQ
workers or active executions. Check their declared runtime/init image pins against
the verified release manifest; actual worker image IDs and probes are checked
after restoration. Before queue resume, require all sixteen report groups and all
27 default snapshots under the current report policy, with their freshness and
dependency checks passing. A partial set, a timed-out query or a failed freshness
calculation blocks resume, worker restoration and release publication even when
public APIs are Ready. Both publishers must expose fresh health markers and
metrics; ready HTTP pods alone do not establish fresh read models. Confirm
the read-model pool has no queued clients and interactive requests retain
their existing connection capacity.

Compare saved stages, counts, grouping, ordering and blocker targets with the
read-only authoritative lifecycle sample. Verify public reader/feed/version
headers, authentication redirects and shared reader behavior. With an existing
authorized admin or partner session, verify populated boards, membership
boundaries and actual HTTP latency without issuing retries or other mutations.
If no session is accessible, record that HTTP/UI verification gap and validate
current report policies, all 27 snapshots and bounded article/source service
reads in a guarded read-only transaction. Report those service/database timings
separately from authenticated HTTP latency. Overview GETs can enqueue refreshes
when snapshots are stale; read saved reports directly for mutation-free checks.
Observe `DevFeedReadModelLag` and `DevFeedReadModelPublisherStalled` independently
of HTTP readiness.

After the schema, complete pipeline, all 27 reports, freshness, core image/readiness
and Fleet gates pass,
resume RQ through a Fleet Job that atomically deletes only the matching owned
pause while worker and scheduler replicas remain zero. Require the new 0.1.2
runtime, schema `0034`, durable owner state and observed bridge settlement.
Refuse a foreign or unexpectedly expired pause, and verify the owned resume Job
succeeded and the pause is absent before proceeding.

Then restore the recorded thirteen worker Deployments to fifteen replicas and
the scheduler to one replica together through a final Fleet revision. Synchronize
their workload catalog counts. Verify the full release cohort's actual image IDs,
normal worker probes and registration, all desired replicas Ready, no new
container restarts, Fleet desired/applied equality, background heartbeats and
new-event catchup before beginning
the ordinary-work observation window. Do not force or requeue jobs to manufacture
load; queued records alone do not prove active processing.

The updated Codex runtime unloads inactive request-scoped analysis threads promptly.
Keep its existing memory limit and the three article-analysis replicas. Observe
ordinary analysis work for more than 30 minutes, recording loaded thread counts,
RSS and working-set memory, OOM/restart/probe counters, active deliveries and
completed analysis jobs. Confirm completed requests unload while active turns
finish successfully. Require actual starts and completions, no unexpected restarts
and no OOM kills throughout the observation window before publishing the GitHub
release or submitting extensions to stores. Immediate readiness alone cannot
establish memory stability.

Preserve schema `0034` during recovery and roll forward with compatible images.
Keep the release image, GitOps deployment, migration, website, Chrome store and
Edge store status as separate verified results.
