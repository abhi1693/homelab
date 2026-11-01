# Cilium

Fleet owns the existing `kube-system/cilium` Helm release after Ansible installs
the initial CNI. The chart stays pinned to **1.20.1** because the node kernel
constraint documented in the Ansible README still applies. No namespace is
created, adopted, or relabeled by this bundle.

`values.yaml` contains the full bootstrap values. Keep it semantically equal to
`infrastructure/ansible/roles/cilium/templates/values.yaml.j2` rendered with the
home inventory; `scripts/check-cilium-observability.py` checks this contract.
The Ansible role detects the Fleet HelmOp and skips subsequent CLI installs or
upgrades, while retaining bootstrap and read-only validation entrypoints.

Agent metrics listen on **9962**, operator metrics on **9963**, and Hubble
metrics on **9965**. Hubble caches 4095 recent flows per node and exports DNS,
drop, TCP, flow, and ICMP aggregates. Context labels contain namespaces only;
there are no source/destination IP, pod, workload, or DNS-query labels. Relay
and UI remain disabled. The chart maintains Hubble peer mTLS certificates;
there is no public Hubble ingress or persistent flow export.

Prometheus objects belong to the separate
[`cilium-monitoring`](../cilium-monitoring/README.md) bundle, so the CNI does not
depend on Prometheus CRDs during bootstrap. One agent or Envoy node may be
unavailable during a rollout; operators retain two replicas with zero permitted
unavailability. `rollOutCiliumPods` reloads startup configuration through a
normal DaemonSet rollout when the ConfigMap changes. Drift correction never
uses forced resource replacement.

Fleet is the runtime Helm owner. Keep Ansible's bootstrap values and this
bundle semantically equal, validate rendered changes before rollout, and verify
all node agents, Envoys, both operators, metrics targets and application traffic
after reconciliation. Do not repeat ownership adoption during ordinary upgrades.

Validate locally:

```sh
scripts/check-cilium-observability.py
kubectl kustomize kubernetes/projects/system/apps/cilium
kubectl kustomize kubernetes/projects/system/apps/cilium-monitoring
cd infrastructure/ansible
ansible-playbook --syntax-check playbooks/cilium.yml
ansible-playbook playbooks/cilium.yml -e cilium_entrypoint=validation
```

Only the last command inspects hosts; all other commands validate repository
configuration. Rollbacks are Git changes to this bundle. Ansible bootstrap
must not become a second runtime Helm owner.

Upstream references: [metrics](https://docs.cilium.io/en/stable/observability/metrics/),
[per-node configuration and restart requirements](https://docs.cilium.io/en/stable/configuration/per-node-config/),
and the pinned [1.20.1 chart](https://github.com/cilium/cilium/tree/v1.20.1/install/kubernetes/cilium).

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `kube-system/cilium/cilium-agent` | 100m → 150m | 384Mi → 512Mi | 768Mi → 768Mi |
| `kube-system/cilium-envoy/cilium-envoy` | 25m → 25m | 64Mi → 96Mi | 256Mi → 256Mi |

The follow-up memory review sets Envoy requests to `80Mi` (from `96Mi`),
releasing `128Mi` across eight nodes. The fourteen-day per-container peak was
`73Mi`, with no recorded OOM events; the `256Mi` limit remains unchanged.
Bootstrap inventory uses the same `80Mi` request. The agent, operator, network
configuration, and one-at-a-time rolling strategy remain unchanged.
