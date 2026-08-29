---
title: Kubernetes CPU Overcommit
---

# KubeCPUOvercommit

## Meaning

`KubeCPUOvercommit` warns that scheduled pod CPU requests cannot fit if the
largest node is lost. It is a scheduler-capacity alert, not a current CPU-usage
alert. `kubectl top` can be quiet while this alert fires.

## Impact

- A node failure can leave replacement pods Pending even when the surviving
  nodes are otherwise healthy.
- Reducing requests without workload evidence can move the risk from the
  scheduler into runtime throttling or saturation.
- A singleton `Recreate` workload has a real serving gap whenever a request
  change rolls its pod.

## Diagnosis

Calculate the same N-1 capacity boundary from kube-state-metrics:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:9090/proxy/api/v1/query?query=sum(namespace_cpu:kube_pod_container_resource_requests:sum)%20-%20(sum(kube_node_status_allocatable%7Bjob%3D%22kube-state-metrics%22%2Cresource%3D%22cpu%22%7D)%20-%20max(kube_node_status_allocatable%7Bjob%3D%22kube-state-metrics%22%2Cresource%3D%22cpu%22%7D))' \
  | jq -r '.data.result[] | .value[1]'
```

List the largest pod requests before choosing a target:

```sh
kubectl get pods -A -o json \
  | jq -r '
      .items[]
      | select(.status.phase == "Running")
      | [
          .metadata.namespace,
          .metadata.name,
          ([.spec.containers[].resources.requests.cpu // "0"] | join("+"))
        ]
      | @tsv'
```

Use retained Prometheus history for the candidate workload. Compare p95 and
peak CPU over at least seven days, and preserve meaningful headroom above the
observed peak. Check startup, scan, backup, and transcoding periods separately;
a low steady-state p95 is not sufficient evidence for a bursty workload.

## Mitigation

Prefer the smallest evidence-backed request reduction in the owning Fleet
values. Do not patch the live Deployment as the durable fix. Keep limits high
enough for safe bursts unless a separate runtime policy requires a limit.

For Jellyfin, validate the TrueCharts render and remember that its singleton
`Recreate` strategy causes downtime:

```sh
kubectl kustomize kubernetes/projects/entertainment/apps/media-jellyfin >/dev/null
kubectl apply --dry-run=server \
  -k kubernetes/projects/entertainment/apps/media-jellyfin
```

Commit and push the exact app files, then wait for the child Fleet bundle, the
Deployment, and the replacement pod. Use a break-glass live patch only when an
immediate capacity emergency outweighs the drift and rollout risk.

## Verification

- The N-1 Prometheus expression is at or below zero.
- Fleet shows the Git commit applied.
- The replacement workload is Ready and its health endpoint succeeds.
- Runtime CPU remains below the new request during representative bursts.

## Rollback

Revert the request commit if the workload becomes CPU-starved, fails readiness,
or its latency regresses. Fleet should restore the previous request and perform
the workload's normal rollout strategy.

## References

- `docs/runbooks/kubernetes-resource-policy.md`
- `kubernetes/projects/entertainment/apps/media-jellyfin/README.md`
- Prometheus Operator runbook: <https://runbooks.prometheus-operator.dev/runbooks/kubernetes/kubecpuovercommit/>
