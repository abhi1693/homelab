---
title: K3s Raspberry Pi Node Maintenance
---

# K3s Raspberry Pi Node Maintenance

- **Owner:** Home-lab operator
- **Type:** Maintenance
- **Last verified:** 2026-08-28
- **API-VIP invariant verified:** 2026-08-28
- **Estimated time:** 15–30 minutes per node, excluding long pod termination
  grace periods or an approved Git/Fleet preparation change

## Meaning

Use this runbook to take exactly one `k8s-rpi` node out of service for physical
maintenance, shut it down cleanly, and return it to the K3s cluster afterward.
It covers workers and the three control-plane/etcd nodes.

This procedure uses the repository helpers:

- `scripts/safe-node-shutdown.sh` cordons, drains with PodDisruptionBudgets
  respected, waits for blocking Longhorn attachments to clear, invokes the
  node-local rack-ops shutdown helper, and waits for the node to become
  `NotReady`.
- `scripts/post-node-power-on.sh` waits for the node to become `Ready`,
  uncordons it, and waits for node-local system pods.

Do not cycle a second node until the first node has completed every recovery
gate in this runbook.

## Impact

- Workloads on the target node are evicted and rescheduled. Singleton workloads
  may have a serving gap while their replacement starts.
- A control-plane shutdown temporarily reduces the embedded-etcd cluster from
  three members to two. A second control-plane outage would lose quorum.
- Longhorn volumes that have a replica on the target may report `degraded`
  while the node is offline, but an attached workload volume must move away
  from the target before shutdown.
- The UPS monitoring Deployment is pinned to `k8s-rpi1` because the USB device
  is physically attached there. It is unavailable while `k8s-rpi1` is off.
- Fleet's generated agents tolerate unschedulable and unreachable control-plane
  nodes. Two replicas use required hostname anti-affinity, so one remains
  available even if a replacement binds to the offline target. The replacement
  may remain Pending until that node returns.
- Prometheus has two hard-anti-affined replicas, independent RWO Longhorn
  claims, a 600-second termination grace period, and a PDB with
  `minAvailable: 1`. One healthy replica can be drained without changing the
  PDB. Stop and recover monitoring first if the PDB allows zero disruptions.
- Jellyfin also runs as one replica with `minAvailable: 1`. Its TrueCharts
  values schema requires `minAvailable` to be present and non-empty, so its
  temporary Git/Fleet maintenance value is `0`, not `null`.

### API-VIP failover invariant

The host-networked kube-vip DaemonSet uses `127.0.0.1:6443` as
`KUBERNETES_SERVICE_HOST`, so every replica talks to the K3s API on its own
control-plane node. Do not replace that endpoint with the registration VIP or
one control-plane node's physical address: kube-vip must be able to renew or
acquire `kube-system/plndr-cp-lock` before the API VIP `192.168.3.2:6443`
exists and while any one server is offline.

The standard procedure verifies this invariant before every control-plane
maintenance window. Repair a mismatch through the Ansible `kube_vip` role;
never patch the live DaemonSet.

## Prerequisites

- Run commands from the repository root.
- Have a working `kubectl` context for the local cluster, `curl`, and `jq`.
- Keep physical access to the target node and its power source.
- Reserve enough time for the longest pod termination grace period reported by
  the preflight inventory.
- Ensure no other node maintenance, K3s upgrade, Longhorn rebuild, storage
  migration, or active incident is in progress.
- Do not use `kubectl patch`, `kubectl delete`, `kubectl scale`,
  `kubectl rollout restart`, or `--disable-eviction` during this procedure.
  Those require explicit break-glass approval in the current maintenance
  window.

Set and validate the exact target. Change only the first line:

```bash
export MAINT_NODE=k8s-rpi2

case "$MAINT_NODE" in
  k8s-rpi[1-8]) ;;
  *) printf 'invalid maintenance node: %s\n' "$MAINT_NODE" >&2; exit 1 ;;
esac

export MAINT_NODE_IP
MAINT_NODE_IP=$(kubectl get node "$MAINT_NODE" \
  -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
printf 'maintenance target: %s (%s)\n' "$MAINT_NODE" "$MAINT_NODE_IP"
```

Expected output is the requested node and its `192.168.3.x` address. Stop if
the name or address is not the physical node being serviced.

## Diagnosis

Complete every preflight gate before running the shutdown helper.

### 1. Require all nodes to be Ready and schedulable

```bash
kubectl get nodes -o wide

kubectl get nodes -o json | jq -r '
  .items[]
  | select(
      (.spec.unschedulable // false)
      or (([.status.conditions[]
            | select(.type == "Ready" and .status == "True")]
           | length) == 0)
    )
  | [.metadata.name,
     (.status.conditions[] | select(.type == "Ready") | .status),
     (.spec.unschedulable // false)]
  | @tsv
'
```

Expected output from the second command: no rows. If another node is
`NotReady` or cordoned, stop. Recover that node before starting a new window.

For a control-plane target, also confirm all three peers are currently Ready:

```bash
kubectl get nodes -l node-role.kubernetes.io/control-plane -o wide
```

Expected output: `k8s-rpi1`, `k8s-rpi2`, and `k8s-rpi3`, all `Ready`. The
shutdown helper performs this quorum preflight again immediately before the
drain.

### 2. Check the kube-vip node-local API dependency

```bash
export KUBE_VIP_API_HOST
KUBE_VIP_API_HOST=$(kubectl -n kube-system get daemonset kube-vip-ds -o json \
  | jq -r '
      .spec.template.spec.containers[]
      | select(.name == "kube-vip")
      | .env[]
      | select(.name == "KUBERNETES_SERVICE_HOST")
      | .value
    ')

printf 'target=%s kube-vip-api-host=%s\n' \
  "$MAINT_NODE_IP" "$KUBE_VIP_API_HOST"

if [[ "$KUBE_VIP_API_HOST" != "127.0.0.1" ]]; then
  printf 'STOP: kube-vip is not using its node-local K3s API\n'
else
  printf 'PASS: every kube-vip replica uses its node-local K3s API\n'
fi
```

Expected output for every maintenance target: `kube-vip-api-host=127.0.0.1`
and `PASS`. If it prints `STOP`, do not cordon or drain the target through this
runbook.

Confirm the API VIP and its leader lease are healthy:

```bash
curl -ksS --connect-timeout 3 -o /dev/null \
  -w 'api_vip_http=%{http_code} connect=%{time_connect} total=%{time_total}\n' \
  https://192.168.3.2:6443/readyz

kubectl -n kube-system get lease plndr-cp-lock \
  -o custom-columns='HOLDER:.spec.holderIdentity,RENEW:.spec.renewTime,DURATION:.spec.leaseDurationSeconds'
```

Expected output: HTTP `401` proves the unauthenticated probe reached the API,
the lease holder is a Ready control-plane node, and `RENEW` is current. A
timeout, empty holder, or stale renewal is a stop condition.

### 3. Require storage and platform controllers to be healthy

```bash
kubectl -n longhorn-system get nodes.longhorn.io \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,SCHEDULABLE:.status.conditions[?(@.type=="Schedulable")].status'

kubectl -n longhorn-system get volumes.longhorn.io -o json | jq -r '
  .items[]
  | select(.status.robustness != "healthy")
  | [.metadata.name,
     .status.kubernetesStatus.namespace,
     .status.kubernetesStatus.pvcName,
     .status.state,
     .status.robustness,
     .status.currentNodeID]
  | @tsv
'

kubectl -n postgresql get clusters.postgresql.cnpg.io \
  -o custom-columns='NAME:.metadata.name,INSTANCES:.spec.instances,READY:.status.readyInstances,PHASE:.status.phase,PRIMARY:.status.currentPrimary'
```

Expected state:

- every Longhorn node is Ready and schedulable;
- the non-healthy volume query produces no rows;
- PostgreSQL reports three instances, three Ready instances, and
  `Cluster in healthy state`.

Stop on degraded or faulted storage, an active replica rebuild, or PostgreSQL
with fewer than three Ready instances.

Check the controllers needed to survive a control-plane drain:

```bash
kubectl -n kube-system get deployment \
  cilium-operator coredns metrics-server traefik \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'

kubectl -n cattle-system get deployment rancher \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'

kubectl -n cattle-fleet-local-system get deployment fleet-agent \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'
```

Expected state: Cilium, CoreDNS, metrics-server, and Traefik are `2/2`; Rancher
is `3/3`; and the Fleet agent is `1/1`.

Confirm Fleet has no unapplied or stalled home-lab source before deliberately
removing another node:

```bash
kubectl -n fleet-local get gitrepos.fleet.cattle.io \
  -o custom-columns='NAME:.metadata.name,READY:.status.readyClusters,DESIRED:.status.desiredReadyClusters,BUNDLES:.status.display.readyBundleDeployments,READY_CONDITION:.status.conditions[?(@.type=="Ready")].status,STALLED:.status.conditions[?(@.type=="Stalled")].status'
```

Expected state: every row has `READY=DESIRED`, every bundle count is `x/x`,
`READY_CONDITION=True`, and `STALLED` is empty or `False`. Do not begin another
control-plane shutdown while Fleet reports `WaitApplied`, `NotReady`, or a
failed Git clone.

### 4. Inventory target workloads, grace periods, PDBs, and attachments

```bash
kubectl get pods -A --field-selector "spec.nodeName=${MAINT_NODE}" -o json \
  | jq -r '
      .items[]
      | [.metadata.namespace,
         .metadata.name,
         (.metadata.ownerReferences[0].kind // ""),
         (.metadata.ownerReferences[0].name // ""),
         .status.phase,
         (.spec.terminationGracePeriodSeconds // 0)]
      | @tsv
    ' \
  | sort -k6,6nr

kubectl get poddisruptionbudgets -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,MIN_AVAILABLE:.spec.minAvailable,MAX_UNAVAILABLE:.spec.maxUnavailable,ALLOWED:.status.disruptionsAllowed'

kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns='NAME:.metadata.name,PVC_NS:.status.kubernetesStatus.namespace,PVC:.status.kubernetesStatus.pvcName,REPLICAS:.spec.numberOfReplicas,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID' \
  | awk -v node="$MAINT_NODE" 'NR == 1 || $NF == node'
```

Review any long-running worker, backup, scan, migration, or CronJob before the
window. Do not force-delete bounded work merely to finish the drain.

Check that Prometheus has enough availability for one replica to move:

```bash
export PROMETHEUS_TARGET_PODS PROMETHEUS_PDB_ALLOWED
PROMETHEUS_TARGET_PODS=$(kubectl -n cattle-monitoring-system get pods \
  -l operator.prometheus.io/name=rancher-monitoring-prometheus \
  -o json \
  | jq --arg node "$MAINT_NODE" \
      '[.items[] | select(.spec.nodeName == $node)] | length')
PROMETHEUS_PDB_ALLOWED=$(kubectl -n cattle-monitoring-system get pdb \
  rancher-monitoring-prometheus \
  -o jsonpath='{.status.disruptionsAllowed}')

printf 'prometheus-pods-on-target=%s allowed-disruptions=%s target=%s\n' \
  "$PROMETHEUS_TARGET_PODS" "$PROMETHEUS_PDB_ALLOWED" "$MAINT_NODE"

if [[ "$PROMETHEUS_TARGET_PODS" != "0" \
   && "$PROMETHEUS_PDB_ALLOWED" == "0" ]]; then
  printf 'STOP: recover Prometheus availability before draining this node\n'
else
  printf 'PASS: Prometheus does not block this target\n'
fi
```

Expected output before the normal procedure: `PASS`. If it prints `STOP`, do
not weaken or bypass the PDB. Restore both Prometheus replicas and their
Longhorn volumes, then repeat the preflight.

Check the single-replica Jellyfin blocker the same way:

```bash
export JELLYFIN_NODE JELLYFIN_PDB_ALLOWED
JELLYFIN_NODE=$(kubectl -n media get pods \
  -l app.kubernetes.io/instance=jellyfin \
  -o jsonpath='{.items[0].spec.nodeName}')
JELLYFIN_PDB_ALLOWED=$(kubectl -n media get pdb jellyfin-main \
  -o jsonpath='{.status.disruptionsAllowed}')

printf 'jellyfin-node=%s allowed-disruptions=%s target=%s\n' \
  "$JELLYFIN_NODE" "$JELLYFIN_PDB_ALLOWED" "$MAINT_NODE"

if [[ "$JELLYFIN_NODE" == "$MAINT_NODE" \
   && "$JELLYFIN_PDB_ALLOWED" == "0" ]]; then
  printf 'STOP: Jellyfin PDB blocks this drain\n'
else
  printf 'PASS: Jellyfin does not block this target\n'
fi
```

If this prints `STOP`, use the Jellyfin preparation below. Its expected blast
radius is one Jellyfin restart and a brief serving gap while the replacement
starts on another node.

## Mitigation

### Optional: prepare the Jellyfin PDB through Git/Fleet

Use this only when Jellyfin is on the target and `jellyfin-main` allows zero
disruptions. In
`kubernetes/projects/entertainment/apps/media-jellyfin/values.yaml`, make this
temporary change:

```diff
 podDisruptionBudget:
   main:
     enabled: true
     targetSelector: main
-    minAvailable: 1
+    minAvailable: 0
```

Do not set this chart's `minAvailable` to `null`; TrueCharts 23.5.0 rejects
that value before applying the Helm release. Use the same scoped Git review,
commit, and push sequence as above, but stage only the Jellyfin values path and
use commit subject `Allow Jellyfin node maintenance`.

Wait for `fleet-local/home-lab-entertainment` to report the exact commit and
all bundles Ready. Continue only when `media/jellyfin-main` shows
`MIN_AVAILABLE=0`, `ALLOWED` is at least `1`, and the Jellyfin Deployment is
`1/1` Ready and Available. Record the commit for restoration.

### 1. Start failover watchers for a control-plane target

Skip this step for a worker. Before shutting down `k8s-rpi1`, `k8s-rpi2`, or
`k8s-rpi3`, keep each command running in a separate terminal:

```bash
while true; do
  curl -ksS --connect-timeout 1 --max-time 2 -o /dev/null \
    -w "$(date -Ins) api_vip_http=%{http_code} connect=%{time_connect}\n" \
    https://192.168.3.2:6443/readyz || true
  sleep 0.5
done
```

```bash
kubectl -n kube-system get lease plndr-cp-lock --watch \
  -o custom-columns='RENEW:.spec.renewTime,HOLDER:.spec.holderIdentity'
```

A short API gap while the five-second leader lease, election, and ARP ownership
converge can occur when the target held the lease. The API must recover with a
Ready control-plane holder; if the target was the holder, that holder must
change. If the API remains unreachable for 15 seconds or the powered-off node
remains holder, restore that node and stop the maintenance sequence.

During the 2026-08-28 kube-vip rollout, replacing the leader pod produced two
failed half-second probes before rpi1 reacquired the lease. The remaining 358
probes succeeded. Treat that as a convergence baseline, not a guarantee that
every network client will observe the same interval.

During the subsequent clean rpi1 shutdown test, the API VIP was unavailable
for approximately 6.25 seconds before rpi2 acquired the lease and advertised
the VIP. The nominal five-second lease does not include all election and ARP
convergence overhead.

### 2. Run the guarded shutdown

```bash
scripts/safe-node-shutdown.sh "$MAINT_NODE"
```

Expected successful sequence:

```text
Control-plane/etcd quorum preflight passed
Cordoning <node>
Draining <node> with PDBs respected
node/<node> drained
Waiting for Longhorn volumes to detach
Requesting clean host shutdown
"shutdown_requested": true
<node> is no longer Ready
```

The helper may take up to the longest workload grace period plus the configured
drain timeout. It does not force a PDB violation. If it exits early, do not
request host shutdown manually; use the matching troubleshooting path below.

If the Rancher-proxied kubeconfig disconnects after evictions have started,
confirm through a non-target control-plane node that the target is still Ready
and cordoned, no Longhorn volume remains attached, and only DaemonSets,
InstanceManager, or the generated Fleet agent remain. Then resume from that
healthy peer so the control path survives the target shutdown. Set the peer IP
to `192.168.3.191` for rpi2 or `192.168.3.108` for rpi3:

```bash
export MAINT_CONTROL_PLANE_IP=192.168.3.191

ssh "asaharan@${MAINT_CONTROL_PLANE_IP}" \
  "sudo -n env DRAIN_POD_SELECTOR='longhorn.io/component!=instance-manager,app!=fleet-agent' bash -s -- '$MAINT_NODE'" \
  < scripts/safe-node-shutdown.sh
```

This exception deliberately leaves only the generated Fleet agent for host
shutdown because its tolerations otherwise bind it repeatedly to the cordoned
target. Do not use the exception while any other ordinary workload or blocking
Longhorn attachment remains.

### 3. Prove the node is safe for physical work

```bash
kubectl get node "$MAINT_NODE" -o wide
ping -c 3 -W 1 "$MAINT_NODE_IP" || true

kubectl get pods -A --field-selector "spec.nodeName=${MAINT_NODE}" -o json \
  | jq -r '
      .items[]
      | select((.metadata.ownerReferences[0].kind // "") != "DaemonSet")
      | select((.metadata.ownerReferences[0].kind // "") != "InstanceManager")
      | [.metadata.namespace,
         .metadata.name,
         (.metadata.ownerReferences[0].kind // ""),
         .status.phase]
      | @tsv
    '

kubectl -n longhorn-system get volumes.longhorn.io -o json | jq -r \
  --arg node "$MAINT_NODE" '
    .items[]
    | select(.status.currentNodeID == $node)
    | [.metadata.name,
       .status.kubernetesStatus.namespace,
       .status.kubernetesStatus.pvcName,
       .spec.numberOfReplicas,
       .status.robustness]
    | @tsv
  '
```

Expected state:

- the node is `NotReady,SchedulingDisabled`;
- ping receives no replies;
- there are no ordinary non-DaemonSet workloads on the node;
- no blocking Longhorn volume is attached to the node. The shutdown helper's
  documented one-replica exception, `media/media-downloads`, must be understood
  and explicitly accepted if it appears.

The API can retain stale `Running` status for DaemonSet and InstanceManager
pods on a powered-off node. Do not treat that cached status as evidence the host
is still on.

### 4. Perform the physical maintenance

Remove or service only the node confirmed by `MAINT_NODE` and `MAINT_NODE_IP`.
Do not power off or disconnect another cluster node during this window.

## Verification and recovery

### 1. Power on and recover the target

After physical work is complete, restore power and run:

```bash
scripts/post-node-power-on.sh "$MAINT_NODE"
```

Expected output: the node becomes `Ready`, is uncordoned, and its Cilium,
Longhorn, monitoring, and rack-ops node-local pods settle. The script does not
move already-relocated workloads back; normal scheduling decides future
placement.

### 2. Re-run the platform recovery gates

```bash
kubectl get nodes -o wide

curl -ksS --connect-timeout 3 -o /dev/null \
  -w 'api_vip_http=%{http_code} connect=%{time_connect} total=%{time_total}\n' \
  https://192.168.3.2:6443/readyz

kubectl -n kube-system get lease plndr-cp-lock \
  -o custom-columns='HOLDER:.spec.holderIdentity,RENEW:.spec.renewTime,DURATION:.spec.leaseDurationSeconds'

kubectl -n kube-system get deployment \
  cilium-operator coredns metrics-server traefik \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'

kubectl -n cattle-system get deployment rancher \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'

kubectl -n cattle-fleet-local-system get deployment fleet-agent \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'

kubectl -n longhorn-system get volumes.longhorn.io -o json | jq -r '
  .items[]
  | select(.status.robustness != "healthy")
  | [.metadata.name,
     .status.kubernetesStatus.namespace,
     .status.kubernetesStatus.pvcName,
     .status.state,
     .status.robustness]
  | @tsv
'

kubectl -n postgresql get clusters.postgresql.cnpg.io \
  -o custom-columns='NAME:.metadata.name,INSTANCES:.spec.instances,READY:.status.readyInstances,PHASE:.status.phase,PRIMARY:.status.currentPrimary'

kubectl -n fleet-local get gitrepos.fleet.cattle.io \
  -o custom-columns='NAME:.metadata.name,READY:.status.readyClusters,DESIRED:.status.desiredReadyClusters,BUNDLES:.status.display.readyBundleDeployments,READY_CONDITION:.status.conditions[?(@.type=="Ready")].status,STALLED:.status.conditions[?(@.type=="Stalled")].status'
```

The maintenance is recovered only when:

- every node is Ready and schedulable;
- the API VIP responds, the kube-vip lease is current, and its holder is Ready;
- Cilium, CoreDNS, metrics-server, and Traefik are 2/2;
- Rancher is 3/3 and Fleet agent is 1/1;
- every Longhorn volume is healthy and PostgreSQL is 3/3;
- every home-lab GitRepo has its desired Ready count and no stalled state.

Check for active pods that are Running but not Ready:

```bash
kubectl get pods -A -o json | jq -r '
  .items[]
  | select(.status.phase == "Running")
  | select(any(.status.containerStatuses[]?; .ready != true))
  | [.metadata.namespace,
     .metadata.name,
     ([.status.containerStatuses[]?
       | "\(.name)=\(.ready)"] | join(",")),
     ([.status.containerStatuses[]?.restartCount] | add // 0)]
  | @tsv
'
```

Expected output: no rows. Time-box startup recovery rather than immediately
restarting slow storage-backed workloads.

### 3. Restore the temporary Jellyfin PDB, if changed

Restore `podDisruptionBudget.main.minAvailable: 1`, commit only
its values path with subject `Restore Jellyfin disruption protection`, and
wait for `home-lab-entertainment` to be fully Ready. Confirm `jellyfin-main`
shows `MIN_AVAILABLE=1` and Jellyfin remains `1/1` Ready before closing the
window.

## Rollback and abort

### Abort before the shutdown request

If the helper cordoned the node but stopped on a transient API error, a PDB, or
a drain timeout while the node is still Ready, return it to service with:

```bash
scripts/post-node-power-on.sh "$MAINT_NODE"
kubectl get node "$MAINT_NODE" -o wide
```

Expected state: `Ready` without `SchedulingDisabled`. Evicted workloads may
remain on their replacement nodes; moving them back is not required for the
rollback.

### Abort after the shutdown request

A completed shutdown cannot be undone through Kubernetes. Restore power, then
run the normal recovery command:

```bash
scripts/post-node-power-on.sh "$MAINT_NODE"
```

Do not remove the Node object or force-delete its stale pods while it is off.

## Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| `Bad Gateway`, `context canceled`, or `rancher.home` connection refused during `kubectl drain` | The Rancher API proxy or its Traefik/MetalLB path briefly lost a backend while control-plane and ingress pods relocated. | Confirm through a non-target control-plane node that the API VIP responds, the target is still Ready and cordoned, replacement controllers are healthy, and no blocking volume remains. Use the documented peer-resume command only if the generated Fleet agent is the sole remaining ordinary workload. If aborting, run the post-power-on helper to uncordon. Do not force-delete pods. |
| `kubectl` through `rancher.home` returns `Unauthorized` | The Rancher-proxied kubeconfig credential expired even though the K3s API is healthy. | Refresh the Rancher kubeconfig. For an active window, use direct `sudo k3s kubectl` access on a healthy non-target control-plane node and the checked peer-resume procedure above. Keep all normal preflight and abort gates in force. |
| `Cannot evict pod as it would violate the pod's disruption budget` | A protected singleton such as Jellyfin is on the target, or a replicated service such as Prometheus is already degraded. | Stop. For Jellyfin, use the Git/Fleet preparation in this runbook after accepting the serving gap. For Prometheus, recover both replicas and storage first. Never add `--disable-eviction` without explicit break-glass approval. |
| Jellyfin HelmOp reports `Expected the defined key [minAvailable] ... to not be empty` | The maintenance change used `minAvailable: null`, which this chart rejects. | Set `podDisruptionBudget.main.minAvailable: 0` through Git/Fleet, wait for the HelmOp and Jellyfin Deployment to become Ready, and only then retry the drain. |
| Drain appears stuck for up to ten minutes | Prometheus has a 600-second grace period, or another workload has bounded shutdown work. | Re-run the workload inventory, inspect the owning controller and logs, and wait within the declared grace period. Do not force a bounded worker or TSDB shutdown. |
| Longhorn detach times out | A workload still uses a volume on the target, or storage is rebuilding. | Do not power off. Inspect the printed volume/PVC, find its mounting pod, and wait for a healthy detach. Abort and uncordon if the storage state cannot be made healthy in the window. |
| API VIP `192.168.3.2:6443` times out after any control-plane node shuts down | kube-vip leader election cannot reach a surviving node-local API, or the live DaemonSet no longer has `KUBERNETES_SERVICE_HOST=127.0.0.1`. | Restore the target node, wait for `plndr-cp-lock` to renew, and run the recovery checks. Do not cycle another control-plane node. Compare the live DaemonSet with the Ansible-rendered manifest and repair drift through the `kube_vip` role. |
| Cilium operator becomes 0/2 and logs `no route to host` for `192.168.3.2:6443` | The API VIP is unavailable. | Restore the kube-vip/API path first. Do not restart Cilium; it recovers after API connectivity returns. |
| Fleet GitRepo jobs fail with `lookup github.com: i/o timeout` | DNS and Cilium lost the API during the VIP outage. | Recover the API VIP, Cilium, and CoreDNS; then wait for Fleet to reconcile. Do not start the next node until every GitRepo is Ready and not Stalled. |
| A Fleet agent schedules onto a cordoned/off control-plane node | Its generated tolerations permit unschedulable and unreachable control-plane nodes, so a replacement can bind to the maintenance target. | Confirm the second hostname-separated Fleet agent remains Ready and GitRepos continue reconciling. Restore the node, wait for Fleet agent 2/2, and verify every pending GitRepo revision. Do not delete pods or patch the generated Deployment during routine maintenance. |
| The node becomes unreachable but later returns Ready without operator power-on | `systemctl poweroff` resulted in a reboot or an external power/watchdog path restarted the host. | Compare `.status.nodeInfo.bootID` and Node `Rebooted` events. Treat the node as back in service, run the post-power-on recovery gates, and repeat the shutdown only after the cause and maintenance window are understood. Do not begin maintenance based only on a transient ping failure. |
| Node is Ready after power-on but remains `SchedulingDisabled` | The recovery helper has not run or exited early. | Run `scripts/post-node-power-on.sh "$MAINT_NODE"` and verify the node-local system pods. |
| Longhorn reports volumes `degraded` after shutdown | The powered-off node held one replica. | Confirm every affected volume remains attached elsewhere with healthy running replicas. For sequential maintenance, wait for all volumes to return healthy before cycling another node. |

## Escalation

Stop the procedure and contact the home-lab cluster owner in the active
maintenance channel when any of these conditions persists for 15 minutes:

- fewer than two other control-plane/etcd nodes are Ready;
- the API VIP or kube-vip lease does not recover;
- PostgreSQL remains below 3/3;
- a Longhorn volume is faulted, detached unexpectedly, or lacks a healthy
  replica elsewhere;
- Fleet remains Stalled after API, Cilium, and DNS recovery;
- a PDB must be bypassed or a live controller mutation appears necessary.

Provide the target node, the last successful runbook step, `kubectl get nodes
-o wide`, the failing command and exact error, affected pod/PVC names, and the
most recent relevant controller logs.

## Post-procedure checklist

- [ ] The maintained node is Ready and schedulable.
- [ ] All other nodes remained Ready throughout the window.
- [ ] API VIP, kube-vip lease, Cilium, Fleet, Rancher, CoreDNS, metrics-server,
      and Traefik passed their recovery gates.
- [ ] Longhorn is fully healthy and PostgreSQL is 3/3.
- [ ] All home-lab GitRepos are Ready and not Stalled.
- [ ] Any temporary Jellyfin PDB change is restored to `minAvailable: 1`.
- [ ] User-visible services affected by the move respond normally.
- [ ] The next node is not started until every item above passes.
- [ ] Any command, expected output, or failure path that differed in practice
      is corrected in this runbook while the maintenance evidence is fresh.

## References

- `scripts/safe-node-shutdown.sh`
- `scripts/post-node-power-on.sh`
- `scripts/README.md`
- `infrastructure/ansible/inventories/home/group_vars/k3s_servers.yml`
- `infrastructure/ansible/roles/kube_vip/templates/kube-vip.yaml.j2`
- `kubernetes/projects/system/apps/rancher-monitoring/values.yaml`
- `kubernetes/projects/entertainment/apps/media-jellyfin/values.yaml`
- `kubernetes/projects/system/apps/rancher-monitoring/README.md`
- `kubernetes/projects/home-automation/apps/ups-monitoring/README.md`
- `kubernetes/projects/home-automation/apps/rack-ops-controllers/README.md`
