---
title: K3s and Rancher Upgrade Recovery Points - 2026-08-11
---

# K3s and Rancher Upgrade Recovery Points - 2026-08-11

## Meaning

This checkpoint records the recovery points and live pre-state before a planned
K3s minor upgrade and later Rancher platform upgrade evaluation.

Checkpoint time:

- UTC: `2026-08-11T15:54:25Z`
- Local: `2026-08-11 21:24:25 IST`
- Git desired-state commit applied by Fleet:
  `522d8f6bf7c8b31701e6f37c680bed7b0656e847`
- Local Git note: unrelated NetBox/Diode working-tree changes were present and
  were not part of this checkpoint.

## Recovery Points

### Rancher Backup

The Rancher Backup recurring `nightly` backup is complete and uploaded to S3.

| Field | Value |
| --- | --- |
| Resource | `backups.resources.cattle.io/nightly` |
| Status | `Completed` |
| Conditions | `Ready=True`, `Uploaded=True` |
| Location | `S3` |
| Filename | `nightly-51d2e7c5-5eb8-4baf-9660-63ec684e6fcd-2026-08-11T00-00-00Z.tar.gz` |
| Last snapshot timestamp | `2026-08-11T00:00:37Z` |
| Next snapshot | `2026-08-12T00:00:00Z` |
| ResourceSet | `rancher-resource-set-full` |

### K3s Etcd Snapshot

A fresh host-level K3s etcd snapshot was created on `server-1` / `k8s-rpi1`.

| Field | Value |
| --- | --- |
| Snapshot CR | `local-pre-k3s-minor-upgrade-20260811t155059z-k8s-rpi1-1786463468-ac491a` |
| Snapshot name | `pre-k3s-minor-upgrade-20260811T155059Z-k8s-rpi1-1786463468` |
| Node | `k8s-rpi1` |
| Ready to use | `true` |
| Created | `2026-08-11T15:51:08Z` |
| Size | `140951584` bytes |
| Location | `file:///var/lib/rancher/k3s/server/db/snapshots/pre-k3s-minor-upgrade-20260811T155059Z-k8s-rpi1-1786463468` |

Command used:

```sh
ansible server-1 -m command -a 'k3s etcd-snapshot save --name pre-k3s-minor-upgrade-20260811T155059Z' -b
```

## Pre-State

### Nodes

| Node | Status | Roles | Version | Internal IP | OS | Kernel | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `k8s-rpi1` | `Ready` | `control-plane,etcd` | `v1.35.6+k3s1` | `192.168.3.243` | Debian 13 | `6.18.34+rpt-rpi-2712` | `containerd://2.2.5-k3s2` |
| `k8s-rpi2` | `Ready` | `control-plane,etcd` | `v1.35.6+k3s1` | `192.168.3.191` | Debian 13 | `6.18.34+rpt-rpi-2712` | `containerd://2.2.5-k3s2` |
| `k8s-rpi3` | `Ready` | `control-plane,etcd` | `v1.35.6+k3s1` | `192.168.3.108` | Debian 13 | `6.18.34+rpt-rpi-2712` | `containerd://2.2.5-k3s2` |
| `k8s-rpi4` | `Ready` | worker | `v1.35.6+k3s1` | `192.168.3.135` | Debian 13 | `6.18.34+rpt-rpi-2712` | `containerd://2.2.5-k3s2` |

### Pods

- Total pods: `220`
- Non-running/non-succeeded pods at checkpoint: stale failed pods from prior
  node-taint windows, all on `k8s-rpi1`.

| Namespace | Pod | Phase | Note |
| --- | --- | --- | --- |
| `cattle-monitoring-system` | `alertmanager-rancher-monitoring-alertmanager-1` | `Failed` | stale pod; StatefulSet reports `1/2` ready |
| `cattle-monitoring-system` | `rancher-monitoring-grafana-7ffcf689bc-hdz6x` | `Failed` | stale pod; replacement Deployment is available |
| `harbor` | `harbor-registry-7d98bfc9f6-2fwrn` | `Failed` | stale pod; replacement registry pods are running |
| `media` | `ryokan-fb5445c95-qb65q` | `Failed` | stale pod; replacement Ryokan pod is running |
| `media` | `shoko-567764555c-7sbtp` | `Failed` | stale pod; replacement Shoko pod is running |
| `shipyardhq` | `shipyardhq-6866d6df7b-hfsjq` | `Failed` | stale pod; Deployment is `3/3` available |
| `wardn` | `wardn-ai-api-75fb4f8855-dmqtc` | `Failed` | stale pod; Deployment is `2/2` available |

### Fleet GitRepos

All Fleet GitRepos were ready after the Smart Queues image rollout settled.

| GitRepo | Ready | Desired | Commit |
| --- | --- | --- | --- |
| `home-lab-applications` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-database` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-entertainment` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-fleet` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-home-automation` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-rancher-projects` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-system` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |
| `home-lab-wardn-ai` | `1` | `1` | `522d8f6bf7c8b31701e6f37c680bed7b0656e847` |

No Fleet bundles reported a ready/desired mismatch at final check.

### Helm Releases

- Total Helm releases: `124`
- Key platform releases:

| Release | Namespace | Chart | App Version | Status |
| --- | --- | --- | --- | --- |
| `rancher` | `cattle-system` | `rancher-2.14.3` | `v2.14.3` | `deployed` |
| `fleet` | `cattle-fleet-system` | `fleet-109.0.4+up0.15.4` | `0.15.4` | `deployed` |
| `fleet-crd` | `cattle-fleet-system` | `fleet-crd-109.0.4+up0.15.4` | `0.15.4` | `deployed` |
| `cilium` | `kube-system` | `cilium-1.19.5` | `1.19.5` | `deployed` |
| `longhorn` | `longhorn-system` | `longhorn-109.3.1+up1.11.2` | `v1.11.2` | `deployed` |
| `rancher-backup` | `cattle-resources-system` | `rancher-backup-109.0.5+up10.0.5` | `v10.0.5` | `deployed` |
| `rancher-monitoring` | `cattle-monitoring-system` | `rancher-monitoring-109.0.3+up80.9.1-rancher.14` | `v0.87.1` | `deployed` |
| `loki` | `cattle-monitoring-system` | `loki-7.0.0` | `3.6.7` | `deployed` |
| `netbox` | `netbox` | `netbox-8.3.51` | `v4.6.7` | `deployed` |
| `qbittorrent` | `media` | `qbittorrent-25.6.0` | `5.2.2` | `deployed` |

Known non-platform release status:

- `rancher-compliance-scans` in `compliance-operator-system` was `failed`
  before the upgrade checkpoint.

### Cilium

The local `cilium` CLI was not installed, so status was captured from a Cilium
agent pod and Kubernetes controller readiness.

| Component | Status |
| --- | --- |
| Agent status command | `OK` |
| `DaemonSet/cilium` | `4/4` ready |
| `DaemonSet/cilium-envoy` | `4/4` ready |
| `Deployment/cilium-operator` | `2/2` available |

### Longhorn

- Total Longhorn volumes: `23`
- Healthy attached volumes: `22`
- Non-healthy volume at checkpoint:

| Volume | State | Robustness | Size | Bound PVC |
| --- | --- | --- | --- | --- |
| `pvc-e6d8a127-ac59-4ce2-861c-f0c54f069d0e` | `detached` | `unknown` | `2147483648` | `home-assistant/home-assistant-pvc` |

### Rancher Version

| Source | Version |
| --- | --- |
| `settings.management.cattle.io/server-version` | `v2.14.3` |
| Rancher Deployment image | `rancher/rancher:v2.14.3` |
| Helm release | `rancher-2.14.3`, app `v2.14.3` |

## Verification

Final gate checks:

- Rancher `/ping`: `pong`
- Kubernetes `/readyz`: `readyz check passed`
- Fleet GitRepos: all `READY=1`, `DESIRED=1`
- `qbittorrent-smart-queues`: rollout successful, `1/1` available on image
  `registry.home/ghcr.io/abhi1693/qbittorrent-smart-queues:0.1.76`
- `loki-0`: `2/2 Running`, no deletion timestamp
- NetBox and NetBox worker pods: running

## Rollback

For K3s rollback planning, use the fresh snapshot named
`pre-k3s-minor-upgrade-20260811T155059Z-k8s-rpi1-1786463468` on `k8s-rpi1`.
For Rancher object rollback, use the completed Rancher Backup nightly archive
recorded above.
