# Redis to Valkey cutover

DevFeed uses shared Valkey Sentinel set `valkey`, logical database **10**.
The data URL selects DB 10; Sentinel discovers the writable primary. Both ingress
and egress policies allow only labeled DevFeed clients on ports 6379 and 26379.

## Completed Fleet stages (historical)

1. Expand shared Valkey data memory to a 640Mi request / 1536Mi limit, with
   rolling-update partitions 2, 1, 0. Check each ordinal's readiness and replication
   and Sentinel quorum before advancing. The chart's primary shutdown hook handles
   election. Restore the normal `OnDelete` strategy when all ordinals are verified.
2. Deploy the Sentinel-capable application release with existing Redis settings.
   Enable two replicas, hard hostname anti-affinity and `minAvailable: 1` PDBs for
   both frontends and all three APIs. Disable local database pooling on workers and
   the scheduler to release idle session-pooler slots.
3. Commit zero replicas for all three APIs, both worker deployments and the
   scheduler. Wait for every producer and consumer pod to terminate gracefully.
   The frontends remain running, but API-backed operations are briefly unavailable.
4. Add `valkey-migration-script.yaml` and `valkey-migration-job.yaml` to
   `kustomization.yaml`. The one-time Job must use the verified release digest.
   Confirm completion and its aggregate verification log before resuming clients.
   It refuses a nonempty destination or unsupported types, checks source stability,
   verifies values/absolute expiries, and waits for both replicas to acknowledge.
   Redis 8 DUMP/RESTORE is incompatible with this Valkey version, so the migration
   copies standard values and stream IDs/metadata. It never prints keys or values.
5. Configure the runtime ConfigMap with the Sentinel nodes/master and DB 10 URL,
   remove the old Redis Secret from runtime `envFrom`, and restore replicas.
   Keep the migration Job's source Secret reference and original Redis PVC.
6. Verify Fleet convergence, per-node web/API redundancy, worker registration,
   sessions, public feeds and admin API timings. Scale the dedicated Redis to zero
   only after cutover verification; retain its Deployment, Secret and PVC.

## Failure and rollback

If the migration fails, keep clients paused and inspect its aggregate logs.
Do not blindly rerun or clear DB 10: a partial attempt deliberately fails closed.
Restore the old runtime settings/replicas through Git to resume against the
unchanged Redis source, after confirming no client used the destination.

Once clients have written to Valkey, switching back to the old snapshot would lose
new sessions and queue changes. Rollback then requires another coordinated pause
and a validated reverse copy into an empty destination. Application images older
than v0.0.5 do not understand Sentinel; do not roll them back independently of the
connection configuration.

Remaining single-instance dependencies are the dedicated Codex service, scheduler,
Chimely service and the NFS server holding inbox credentials. Shared Valkey provides
primary failover but asynchronous replication can lose recent unreplicated writes.
The shared cluster, storage and network remain common failure domains.

## Completed cutover evidence

The v0005 Job completed successfully: 49,010 keys copied and verified, 679 keys
expired before/during their copy, and 48,740 keys remained after the final
comparison. Both Valkey replicas acknowledged the writes. All API, worker and
scheduler pods were absent during the copy. The original Redis was retained until cutover verification completed.

Post-cutover checks confirmed Sentinel database 10, the existing admin session
with its original access policy, enabled user/admin sign-in, both HTTPS origins,
and all 20 background plus 5 AI workers ready with zero restarts. The old Redis
Deployment was then scaled to zero. Subsequent cleanup removed the Deployment,
Service, Secret, PVC/PV and one-time copy resources. The PVC keep annotation was
removed and reconciled before pruning; the Longhorn PV used Delete reclaim policy.
The deleted Redis snapshot is no longer a rollback option. A reverse cutover now
requires provisioning an empty destination and copying current Valkey data.

After queues drained, background workers were reduced from 20 to 5; AI workers
remain at 5. All five frontend/API pairs remain at 2 replicas.
