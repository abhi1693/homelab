# K3s server rollout gates

The server play processes inventory hosts one at a time and aborts remaining
batches on failure. `k3s_server_rollout_mode` defaults to `rolling`: every server
must pass the cluster preflight before any configuration, download, or restart.
After the final handler flush, the server must pass the recovery barrier before
Ansible advances. The validation entrypoint runs the same read-only barrier.
Already-matching Node taints are skipped without issuing a mutating API command.

## Prepare before maintenance

From `infrastructure/ansible`:

```sh
ansible-playbook playbooks/k3s_server_tools.yml
ansible-playbook playbooks/k3s_server.yml -e k3s_server_entrypoint=validation
```

The tools play installs only the ARM64 `etcdctl` client from the checksum-pinned
official etcd 3.6.14 release. It does not install an etcd server, alter systemd,
or restart K3s. Re-running it is idempotent. The version, SHA256, and associated
K3s release are in `inventories/home/group_vars/k3s_servers.yml`. Review these
pins together whenever K3s changes, including compatibility with both versions
during the rolling transition. Rolling main and validation do not download tools;
an absent or mismatched client stops the run before maintenance starts.

Before an actual upgrade, retain a fresh verified etcd snapshot and its K3s
server token, review release compatibility, and resolve existing incidents.
Successful checks here do not replace those operator prerequisites.

### Upgrade and recovery

Review the source and target releases, client compatibility, and supported
upgrade path before changing inventory. Validate the running version first;
if desired state already targets a newer version, use reviewed source-version
overrides for validation only. Never use bootstrap mode to bypass rolling gates.

Once the maintenance window is authorized, upgrade servers first, then workers,
using their default rolling main entrypoints. Stop if any gate fails. After
rollout, run both validation entrypoints against the target inventory version.

Retain a fresh on-demand snapshot from a healthy server together with that
server's `/var/lib/rancher/k3s/server/token`. Keep an encrypted copy outside
the cluster and repository, using the existing SOPS age recipient with private
directory/file permissions. Verify decryption, the snapshot's embedded SHA256,
and byte-for-byte hashes of the transferred snapshot and token. Keep the age
identity recoverable independently; encryption without its key is not a backup.
An etcd snapshot does not back up PVC or external NAS application data.
Checksum/decryption verification is not a restore rehearsal. A full recovery
must follow the [K3s snapshot restore procedure](https://docs.k3s.io/cli/etcd-snapshot)
under separate authorization, never an automatic downgrade or membership reset.

## What must pass

- Authenticated `/readyz?verbose` through each server address and the API VIP.
- All Kubernetes Nodes Ready, schedulable, and without pressure conditions.
  Every expected control-plane Node must exist and have a recent Node Lease.
- Local K3s service active and installed version correct after handlers; the
  target's API-observed kubelet version must match the pin. Recovery captures
  the target Lease **after** the final handler flush and waits for another
  renewal, so a cached Ready condition cannot satisfy the barrier alone.
- TLS-authenticated `etcdctl` status, member list, alarm list, and explicit
  linearizable key-only reads against all three endpoints. No key is created.
  Three distinct voting members must match inventory names/peer addresses,
  agree on cluster ID, leader and Raft term, and report no errors or alarms.
  Applied-index lag must be within `k3s_server_etcd_max_index_lag` (1000 entries
  by default). Live indices need not be identical on a busy cluster.
  Membership IDs/names/peer URLs must remain unchanged from preflight.
- A fresh kube-vip lease held by an expected Ready control-plane Node.
- Configured critical Deployments and DaemonSets at their observed generation,
  desired Ready/available/updated counts, with a Ready pod for every configured
  node-local DaemonSet on the target. The inventory includes Cilium, kube-vip,
  Longhorn, node monitoring, DNS, ingress, Rancher, Fleet, and Harbor registry.
- Every Longhorn volume healthy, PostgreSQL clusters at all desired instances
  (at least three), and expected Fleet GitRepos present. Every home-lab GitRepo
  must be Ready, not Stalled, and have no missing, modified, unknown, unready,
  or WaitApplied resources or outstanding bundle deployments.
- Two consecutive successful samples, 20 seconds apart, with an unchanged
  etcd leader/term and critical-namespace pod UID/restart counts. Failed samples
  reset the success counter. Completed/failed Jobs are not pod readiness gates.

The read-only checker runs on the first non-target inventory server using that
server's existing kubeconfig and local etcd client certificates. Certificates
are never copied to the Ansible controller. `k3s_server_readiness_delegate` can
select a different healthy peer, but cannot select the target itself. Endpoints
come from the **full** server inventory even with `--limit server-1`.

The default barrier deadline is 600 seconds, with each command bounded to at
most 15 seconds. `k3s_server_health_timeout`, `k3s_server_health_interval`, and
`k3s_server_health_samples` configure recovery timing; at least two samples and
a 15-second interval are enforced. On failure, the checker reports the last
failed gate and Ansible stops. Diagnose from the healthy peer using the reported
resource/endpoint; do not automatically restart another server, alter membership,
or downgrade the cluster. No automatic repair is part of these gates.

## Bootstrap

`site.yml` explicitly selects `bootstrap` for the server main and validation
passes. Initial servers cannot require a complete three-member cluster, a Ready
Node before Cilium exists, or Fleet workloads before they are installed. Bootstrap
retains local API readiness and service/version checks; it skips the established
cluster barrier. Never use bootstrap mode to bypass an unhealthy existing
cluster. Use the default rolling playbook for subsequent server changes.
The initial worker passes also explicitly select bootstrap mode to defer Node
Ready until Cilium is installed, while retaining service, lease and version checks.

## Verify changes to the gate

```sh
python3 -m unittest discover -s roles/k3s_server/tests -v
ansible-playbook --syntax-check playbooks/site.yml
ansible-playbook --syntax-check playbooks/k3s_server_tools.yml
ansible-playbook playbooks/k3s_server.yml -e k3s_server_entrypoint=validation
```

The tests exercise mismatched membership, learner state, missing endpoints,
leader/term disagreement, excessive lag, incomplete rollouts, stale leases,
unapplied Fleet resources, stability reset, and timeouts without cluster writes.
The live validation proves current reads; it does not simulate a K3s restart.

References: [K3s manual upgrades](https://docs.k3s.io/upgrades/manual),
[etcd client release](https://github.com/etcd-io/etcd/releases/tag/v3.6.14), and
the repository [node maintenance runbook](../../../../docs/runbooks/k3s-node-maintenance.md).
