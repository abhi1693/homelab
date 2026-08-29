---
title: PgBouncer Client Queueing
---

# PgBouncer Client Queueing

## Meaning

`PgBouncerClientQueueing` means at least one client waited for a backend during
the last five minutes and the condition persisted for another five minutes. A
session-mode pool can exhaust its backend budget even when PostgreSQL reports
most sessions as `idle`: each client retains its server connection until the
client disconnects.

## Impact

Queued clients see elevated latency and may exceed their application command
timeout. For Jellyfin this appears as `NpgsqlException`, read timeouts, and
failed API requests even when the PostgreSQL cluster remains healthy.

## Diagnosis

Confirm the alert labels and current metric:

```sh
kubectl -n cattle-monitoring-system exec \
  prometheus-rancher-monitoring-prometheus-0 -c prometheus -- \
  wget -qO- 'http://127.0.0.1:9090/api/v1/alerts'
```

Query the affected PgBouncer instance directly. Use its local administrative
socket so diagnosis does not consume an application backend:

```sh
kubectl -n postgresql exec <pooler-pod> -c pgbouncer -- \
  psql -X -U pgbouncer -h /controller/run pgbouncer -c 'SHOW POOLS;'
```

Interpret the columns together:

- `cl_waiting > 0` with `sv_active == default_pool_size` confirms pool
  exhaustion.
- `sv_idle > 0` suggests a routing or pool-identity issue instead of capacity.
- In session mode, `cl_active` and `sv_active` can remain high while the
  corresponding PostgreSQL sessions are `idle`.

Verify that PostgreSQL has connection and execution headroom before increasing
the pool:

```sh
kubectl -n postgresql exec <primary-pod> -c postgres -- psql -X -d postgres -c \
  "SELECT usename, count(*) AS connections,
          count(*) FILTER (WHERE state = 'active') AS active
     FROM pg_stat_activity
    WHERE backend_type = 'client backend'
    GROUP BY usename ORDER BY connections DESC;
   SELECT count(*) AS used,
          current_setting('max_connections')::int - count(*) AS headroom
     FROM pg_stat_activity;"
```

Check active query wait events and application logs. Do not infer database
pressure from queueing alone.

## Mitigation

Keep the repair GitOps-owned. For a session-mode pool:

1. Determine peak simultaneous client demand from `SHOW POOLS` and Prometheus.
2. Set `instances * default_pool_size` high enough for that demand.
3. Keep total backend capacity at or below the role `connectionLimit`.
4. Preserve PostgreSQL `max_connections` headroom for other roles, replication,
   pooler administration, and operator access.
5. Prefer two pooler replicas for an application that needs availability; use
   anti-affinity or topology spread without pinning either replica to a named
   node.

Do not switch from session to transaction pooling merely to clear the alert.
First prove that the client and driver do not rely on session state, prepared
statements, temporary objects, or session-scoped settings.

After Fleet reconciles the new pooler capacity, recycle only the affected
singleton application pod if its long-lived connections remain concentrated on
the old pooler instance. This is a break-glass action and should not be needed
for ordinary GitOps rollouts.

## Verification

- Both pooler replicas are Ready on different scheduler-selected nodes.
- `SHOW POOLS` reports `cl_waiting = 0` on every instance.
- PostgreSQL remains healthy with adequate connection headroom.
- The application health endpoint succeeds and fresh logs contain no database
  timeouts.
- `PgBouncerClientQueueing` disappears from Prometheus before reaching firing,
  or returns to inactive after the configured `for` window.

## Rollback

Revert the pooler and role limits in Git, allow Fleet to reconcile, and verify
that existing demand fits the restored capacity. Do not lower the PostgreSQL
role limit below the total pooler backend capacity.

## References

- `kubernetes/projects/database/README.md`
- `kubernetes/projects/database/apps/postgresql/values.yaml`
- `kubernetes/projects/entertainment/apps/media-jellyfin/README.md`
