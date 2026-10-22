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

The ownership handoff must precede the feature change:

1. Adopt the same release/chart with exact current Helm user values. Compare
   `helm template` against `helm get manifest`; the baseline must have no
   resource or pod-template changes. Wait for the Fleet HelmOp to become Ready
   and prove agent/operator/Envoy pod UIDs and readiness are unchanged.
2. Publish the monitoring values and separate monitors. Wait for the one-node
   agent rollout, then verify all nodes and Cilium health, both operators, all
   Envoys, all metrics targets, and representative application traffic.

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
