---
title: Node Saturation and Zombie Processes
---

# NodeSystemSaturation And Process Accumulation

## Meaning

`NodeSystemSaturation` fires when one-minute load per CPU core is above `2` for
15 minutes. Load includes runnable and uninterruptible tasks; it is not the same
as CPU utilization. A node can have idle CPU and still have high load from I/O,
process churn, or a large leaking process table.

## Impact

- Kubelet, containerd, Cilium, and application latency can degrade together.
- Blindly lowering one workload's CPU request does not fix runtime saturation.
- Recycling a singleton pod clears leaked processes but creates a service gap
  and does not repair the application bug that leaked them.

## Diagnosis

Read the live alert value and correlate it with node evidence:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:9090/proxy/api/v1/query?query=node_load1%7Bjob%3D%22node-exporter%22%7D%20%2F%20count%20without%20(cpu%2Cmode)%20(node_cpu_seconds_total%7Bjob%3D%22node-exporter%22%2Cmode%3D%22idle%22%7D)' \
  | jq -r '.data.result[] | [.metric.instance,.value[1]] | @tsv'

cd infrastructure/ansible
ansible server-2 -b -m ansible.builtin.shell -a '
  uptime
  vmstat 1 5
  COLUMNS=220 top -b -n 1 | head -35
  ps -e -o stat= | cut -c1 | sort | uniq -c
  ps -eo pid,ppid,stat,wchan:32,comm,args
'
```

If zombies are numerous, group them by parent and map the parent cgroup's pod
UID back to Kubernetes:

```sh
ansible server-2 -b -m ansible.builtin.shell -a \
  "ps -eo ppid=,stat= \
   | awk '\$2 ~ /^Z/ {count[\$1]++} END {for (pid in count) print count[pid], pid}' \
   | sort -nr \
   | head -20"

kubectl get pods -A -o json \
  | jq -r '.items[] | [.metadata.namespace,.metadata.name,.metadata.uid] | @tsv'
```

Inspect the exact parent and its pod logs. In qBittorrent incidents, also read
the smart-queues decision log and distinguish productive workers from stalled
torrents before changing concurrency.

Known local patterns include unreaped `bwrap` children beneath the Wardn Hub
Codex app server and smaller zombie accumulation beneath Profilarr. Recycling
those pods clears the process table, but the durable fix belongs in each
application's child-process lifecycle.

Another observed pattern is a Cilium-to-Envoy xDS acknowledgement loop. The
Cilium agent log repeats `OnStreamRequest` and `OnStreamResponse` with the same
policy snapshot and resource count thousands of times per second while both
`cilium-agent` and `cilium-envoy` consume abnormal CPU. Confirm Cilium otherwise
reports healthy controllers before treating the loop as the cause:

```sh
kubectl -n kube-system top pods | grep -E 'cilium|envoy'
kubectl -n kube-system logs <cilium-pod-on-node> --since=5m \
  | grep -E 'OnStream(Request|Response)' \
  | tail -100
kubectl -n kube-system exec <cilium-pod-on-node> -- cilium-dbg status --verbose
```

## Mitigation

For a bounded download workload, reduce productive concurrency in
`media-qbittorrent/smart-queues-controller.yaml`, validate it, commit it, and
wait for Fleet. Preserve enough parallelism for useful throughput, then prove
the load trend rather than assuming the new number is safe.

For thousands of zombies under a known pod parent, the immediate break-glass
mitigation is to delete only that pod and wait for its owning Deployment to
replace it:

```sh
kubectl -n <namespace> delete pod <exact-pod-name>
kubectl -n <namespace> wait --for=condition=Ready \
  pod -l app.kubernetes.io/name=<app-name> --timeout=180s
```

Confirm replica count, strategy, and user impact first. Singleton `Recreate`
pods have downtime. Restart parents sequentially, never the whole node. File an
application fix when a direct child is not reaped; pod recycling is temporary.

Do not kill zombies individually: they are already dead and only their parent
can reap them. Do not restart k3s merely to clear application-owned zombies.

If a healthy Cilium agent is spending CPU in a proven xDS loop, recycle only
the `cilium-envoy` DaemonSet pod on the affected node first:

```sh
kubectl -n kube-system delete pod <exact-cilium-envoy-pod>
kubectl -n kube-system get pods -l k8s-app=cilium-envoy -o wide
```

This is a break-glass action. Verify the replacement is Ready, the xDS loop has
stopped, and pod networking still works. Do not restart the Cilium agent unless
the loop persists and the wider node-networking interruption is explicitly
accepted.

Control-plane saturation can make CloudNativePG probes time out and trigger an
automatic primary failover. If that occurs, do not interrupt `pg_rewind` on the
old primary. Keep the serving primary and synchronous replica online, then wait
for all three instances to become Ready and streaming:

```sh
kubectl cnpg status -n postgresql postgresql
kubectl -n postgresql get pods -o wide
```

## Verification

- Zombie count returns to zero or a small stable baseline.
- Replacement pods are Ready with stable restart counts.
- Cilium and Envoy return to their normal CPU baseline with no repeating xDS
  request/response loop.
- If CloudNativePG failed over, it returns to 3/3 Ready with both replicas
  streaming and no WAL archive backlog.
- `vmstat` shows sustained idle headroom and low I/O wait.
- `node_load1 / cores` remains below `2` for longer than the alert's 15-minute
  firing window.
- Alertmanager contains neither `NodeSystemSaturation` nor the associated
  `InfoInhibitor`.

## Rollback

Revert a concurrency change through Git if throughput becomes unacceptable.
A deleted pod cannot be restored; its owning controller creates the replacement.

## References

- `kubernetes/projects/entertainment/apps/media-qbittorrent/README.md`
- Prometheus Operator runbook: <https://runbooks.prometheus-operator.dev/runbooks/node/nodesystemsaturation/>
