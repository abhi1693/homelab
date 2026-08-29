---
title: Alertmanager Firing Alert Triage
---

# Alertmanager Firing Alert Triage

## Meaning

Use this runbook to inventory every alert currently known to Alertmanager and
to distinguish a live fault from a retained Kubernetes object. `Watchdog` is
expected to fire continuously. `InfoInhibitor` is a routing helper created by
an underlying `severity="info"` alert; do not repair or silence it directly.

`KubeJobFailed` remains active for as long as a failed Job object exists. It
does not prove that the current CronJob schedule, Fleet revision, or storage
policy is still failing.

## Impact

- A real current fault can be hidden in a large list of historical failed Jobs.
- Deleting every failed Job can erase the evidence needed to find a recurring
  controller, deadline, mount, or OOM failure.
- Treating `Watchdog` or `InfoInhibitor` as workload failures creates noise and
  can damage the alert-routing safety checks.

## Diagnosis

Read the Alertmanager API rather than relying on a notification snapshot:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-alertmanager:9093/proxy/api/v2/alerts' \
  | jq -r '
      .[]
      | [
          .labels.alertname,
          (.labels.severity // "none"),
          (.labels.namespace // ""),
          (.labels.job_name // .labels.instance // ""),
          .status.state,
          (.annotations.description // .annotations.summary // "")
        ]
      | @tsv'
```

For `InfoInhibitor`, find the actual information-level alert in Prometheus:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:9090/proxy/api/v1/alerts' \
  | jq -r '
      .data.alerts[]
      | select(.labels.severity == "info")
      | [.labels.alertname, .state, (.labels.instance // ""), (.annotations.description // "")]
      | @tsv'
```

For each failed Job, preserve its identity and terminal reason before cleanup:

```sh
kubectl get jobs -A -o json \
  | jq -r '
      .items[]
      | select(any(.status.conditions[]?; .type == "Failed" and .status == "True"))
      | [
          .metadata.namespace,
          .metadata.name,
          (.metadata.ownerReferences[0].name // "manual"),
          (.status.conditions[] | select(.type == "Failed") | .reason),
          (.status.conditions[] | select(.type == "Failed") | .message)
        ]
      | @tsv'
```

Then inspect the exact Job and its pod. Do not use a broad label or namespace
delete:

```sh
kubectl -n <namespace> describe job <job-name>
kubectl -n <namespace> get pods -l job-name=<job-name> -o wide
kubectl -n <namespace> logs job/<job-name> --all-containers --tail=200
```

For CronJobs, compare the failed run with newer runs and the live template. For
Fleet-generated Jobs, verify the owning GitRepo and child bundle are healthy at
a newer commit. For one-shot policy Jobs, verify the intended downstream state
directly before declaring the old failure obsolete.

## Mitigation

Fix the durable cause first. Common examples are an NFS ownership walk consuming
the Job deadline, a memory limit causing `OOMKilled`, or a stale Fleet conflict
that a newer reconciliation already resolved.

Failed Job deletion is a break-glass cleanup. It is allowed only after the
exact Job has been diagnosed and either a newer successful run exists or the
intended state is independently proven:

```sh
kubectl -n <namespace> delete job <exact-job-name>
```

Delete only the confirmed objects. Never delete a CronJob, Fleet controller,
Longhorn policy, or all failed Jobs merely to make the alert disappear.

## Verification

Re-read Alertmanager and the failed-Job inventory. A clean result contains only
`Watchdog`; a transient `InfoInhibitor` is acceptable only while its underlying
information-level alert is understood and actively resolving.

```sh
kubectl get jobs -A -o json \
  | jq -r '.items[] | select(any(.status.conditions[]?; .type == "Failed" and .status == "True")) | [.metadata.namespace,.metadata.name] | @tsv'
```

## Rollback

A deleted Job object cannot be restored. Its controller may create a new run,
but its status, events, and pod logs are gone. Capture those first. Roll back
the durable Git change through Git and Fleet if a corrected template regresses.

## References

- `kubernetes/projects/system/apps/rancher-monitoring/README.md`
- [NFS CSI volume ownership storms](storage/nfs-csi-volume-ownership-storms.md)
- [Longhorn disk available space alerts](storage/longhorn-disk-available-space-alerts.md)
- [PgBouncer client queueing](postgresql-pgbouncer-client-queueing.md)
