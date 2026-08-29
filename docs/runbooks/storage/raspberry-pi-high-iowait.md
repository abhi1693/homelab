---
title: Raspberry Pi High I/O Wait
---

# Raspberry Pi High I/O Wait

## Meaning

`RaspberryPiHighIOWait` fires when five-minute CPU I/O wait is above `20%` and
one-minute load is above one runnable or waiting task per CPU core for 15
minutes. Both conditions matter: I/O wait by itself can be high during normal
synchronous Longhorn writes while most CPU remains idle, but a simultaneous
load queue means work is accumulating behind storage.

Do not assume that the physical NVMe is slow. NFS ownership recursion,
Longhorn virtual block latency, PostgreSQL WAL flushes, and a genuinely failing
disk can produce similar node-level metrics.

## First response

Read the live alert and both inputs:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:9090/proxy/api/v1/alerts' \
  | jq -r '.data.alerts[] | select(.labels.alertname == "RaspberryPiHighIOWait")'

kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:9090/proxy/api/v1/query?query=100%20%2A%20avg%20by%20(instance)%20(rate(node_cpu_seconds_total%7Bjob%3D%22node-exporter%22%2Cmode%3D%22iowait%22%7D%5B5m%5D))' \
  | jq -r '.data.result[] | [.metric.instance,.value[1]] | @tsv'

kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:9090/proxy/api/v1/query?query=node_load1%7Bjob%3D%22node-exporter%22%7D%20%2F%20count%20without(cpu%2Cmode)%20(node_cpu_seconds_total%7Bjob%3D%22node-exporter%22%2Cmode%3D%22idle%22%7D)' \
  | jq -r '.data.result[] | [.metric.instance,.value[1]] | @tsv'
```

On the affected node, use bounded samples only:

```sh
cd infrastructure/ansible
ansible server-1 -b -m ansible.builtin.shell -a '
  uptime
  vmstat 1 10
  ps -eo pid,ppid,stat,wchan:32,comm,args \
    | awk '\''substr($3,1,1)=="D"'\'' \
    | head -80
  iostat -dx 1 5
  smartctl -a /dev/nvme0
'
```

Never start an unbounded `du`, `find`, checksum, or ownership walk while the
node is already waiting on storage.

## Route by evidence

### NFS ownership recursion

Look for pods stuck before container startup, `VolumePermissionChangeInProgress`,
and bounded k3s journal entries from `volume_linux.go` or `Lchown failed`.
Follow [NFS CSI volume ownership storms](nfs-csi-volume-ownership-storms.md).

### Longhorn or PostgreSQL synchronous writes

Map blocked processes and mounted devices back to claims, then verify storage
and database health:

```sh
kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
kubectl cnpg status -n postgresql postgresql
kubectl -n postgresql get pods -o wide
```

Healthy evidence is all volumes `healthy`, PostgreSQL instances Ready,
streaming replicas caught up, no failed WAL archive backlog, low physical NVMe
utilization, and no SMART or kernel media errors. Do not reduce replica count,
force a failover, or recreate a database pod merely to move normal write wait.
If load per core is below `1`, the node has no material I/O queue and this alert
should remain inactive even if the raw I/O-wait percentage is above `20%`.

### Physical or capacity pressure

Treat non-zero SMART media errors, kernel reset or I/O errors, high device
utilization, or growing Longhorn latency as a storage incident. Preserve volume
replicas and gather exact device and volume evidence. If Longhorn schedulable
space is the constraint, follow
[Longhorn disk available space alerts](longhorn-disk-available-space-alerts.md)
instead of deleting replicas or lowering reserved space.

## Break-glass boundary

A node service restart is justified only when a verified orphaned kubelet NFS
ownership walk remains after its pod has gone and the other control-plane nodes
are healthy. Check quorum and every workload on the node before and after. A
high metric alone does not authorize restarting k3s, deleting Longhorn objects,
or recycling PostgreSQL.

## Verification

- The combined alert expression returns no series for the affected node.
- `vmstat` shows no sustained blocked-process queue.
- Physical device utilization and latency match the diagnosed workload.
- Longhorn volumes remain healthy and PostgreSQL replication remains current.
- No fresh NFS ownership-walk entries appear in the bounded node journal.
- Alertmanager contains no `RaspberryPiHighIOWait` after the rule's 15-minute
  hold and evaluation delay.

## References

- `kubernetes/projects/system/apps/rancher-monitoring/raspberry-pi-rules.yaml`
- `docs/runbooks/storage/nfs-csi-volume-ownership-storms.md`
- `docs/runbooks/storage/longhorn-disk-available-space-alerts.md`
