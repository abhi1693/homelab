# Cilium

Fleet owns the existing `kube-system/cilium` Helm release after Ansible installs
the initial CNI. Fleet runs chart **1.20.4** after the authorized patch upgrade.
All nine Ubuntu nodes now expose kernel BTF; the 2 November preflight below
clears the historical missing-BTF prerequisite. No namespace is
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
and the pinned [1.20.4 chart](https://github.com/cilium/cilium/tree/v1.20.4/install/kubernetes/cilium).

## Resource sizing

See [kustomization.yaml](kustomization.yaml), [values.yaml](values.yaml) for the configured resources and [the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review) for the historical measurements.

The follow-up memory review sets Envoy requests to `80Mi` (from `96Mi`),
releasing `144Mi` across nine nodes. The fourteen-day per-container peak was
`73Mi`, with no recorded OOM events; the `256Mi` limit remains unchanged.
Bootstrap inventory uses the same `80Mi` request. The agent, operator, network
configuration, and one-at-a-time rolling strategy remain unchanged.

## Upgrade preflight — 2 November 2026

Cilium 1.20.4 preflight passed at 13:14 UTC through the temporary Fleet bundle
introduced in [PR #188](https://github.com/abhi1693/home-lab/pull/188), commit
`15591d3e2253f72e953fc2527752f52341d989ab`. The Cilium release remained 1.20.1.

- All nine Ubuntu 26.04.1 nodes ran `7.0.0-1020-raspi` with readable
  `/sys/kernel/btf/vmlinux` (5,877,901 bytes) and `CONFIG_DEBUG_INFO_BTF=y`.
- The image-preparation DaemonSet reached 9/9 Ready with both containers Ready
  on every node and zero restarts. Running image IDs matched the upstream pins:
  agent `sha256:20fe92e4c86641233a450098c158d2d29085f3419931ab6bf681d2485dedf16e`,
  Envoy `sha256:547ab45f6092f681d9f54f3be9fa8fb1e705c9c5dc2df388efe3a52aa6965629`.
- The target-version validator reached 1/1 Ready. All 25 installed CNPs passed;
  no CCNPs were installed. Its final message was `All CCNPs and CNPs valid!`.
- The three production controllers and twenty production pods retained their
  UIDs. Controller pod templates and all production restart counts matched the
  preflight baseline. Agents/Envoys stayed 9/9 Ready and operators 2/2 Ready.
- Preflight manifests passed server dry run, schema/resource checks, catalog
  validation and all triggered local and hosted checks on the merged commit.

The temporary bundle is removed after evidence capture through Git/Fleet,
including its ServiceAccount and cluster RBAC. Target images remain cached;
normal kubelet image garbage collection may eventually evict them.

To repeat, render chart 1.20.4 with `preflight.enabled=true`, `agent=false`,
`operator.enabled=false`, `k8sServiceHost=192.168.3.2` and `k8sServicePort=6443`.
Deliver an isolated temporary bundle through Fleet and compare its node coverage
with the live Cilium DaemonSet. Keep the deployed Cilium bundle unchanged.
PR #188 records bounded-resource adaptations: no critical scheduling priority,
no host mounts, capability drops, read-only RBAC without Secret access, and no
API-token mount on the image-preparation DaemonSet.

Upstream preflight establishes target-image availability and installed-policy
schema compatibility. It does not start the new agent/Envoy datapath or prove
full target-version runtime behavior, end-to-end traffic or image vulnerability
closure. Recheck live health, policies and image availability immediately before
a separately authorized upgrade. No upgrade is authorized by this result.

## 1.20.4 patch upgrade

The authorized upgrade changes the Fleet chart and bootstrap inventory from
1.20.1 to 1.20.4. Routing, cluster identity, kube-proxy replacement, reservations,
rollout limits and Hubble settings remain unchanged. The chart pins upstream
agent, operator and Envoy images by digest; all three support Linux ARM64.

The relevant benefits are the patched Go trust behavior in the agent/operator,
conntrack/NAT lifetime fixes, concurrent endpoint policy-update fixes, and
correct handling of terminating service backends with traffic distribution.
This cluster enables `loadBalancer.serviceTopology`; cloud-provider IPAM,
ClusterMesh and Gateway API additions do not provide a new enabled feature here.
Upstream references: [1.20.2](https://github.com/cilium/cilium/releases/tag/v1.20.2),
[1.20.3](https://github.com/cilium/cilium/releases/tag/v1.20.3), and
[1.20.4](https://github.com/cilium/cilium/releases/tag/v1.20.4).

A rolling agent/Envoy restart can interrupt userspace-proxied connections; clients
must reconnect. Resource settings are unchanged, but this does not establish
unchanged runtime CPU, memory or throughput. The Pi macb Ethernet driver issue
is separate and is not repaired by this Cilium upgrade.

Validate nine updated agents/Envoys, two updated operators, fresh Pod networking,
DNS/service/ingress traffic, policy behavior and metrics. Require the exact Git
revision and Fleet BundleDeployment desired/applied agreement. Roll back through
a Git revert of the version change, retaining BTF-enabled kernels and the same
values. Do not run a competing Helm/CLI upgrade or disable the Cilium scheduling
taint guard if reconciliation is delayed.

### Rollout and recovery evidence — 2 November 2026

[PR #190](https://github.com/abhi1693/home-lab/pull/190) authorized source pins
and Fleet rollout. At 13:56 UTC all nine nodes, nine target agents, nine target
Envoys and two target operators were Ready. Running image IDs matched the
upstream 1.20.4 agent/operator and chart-selected Envoy digests. Current-pod
Prometheus targets were 9 agents, 9 Hubble exporters and 2 operators healthy;
Cilium, its HelmOp wrapper, monitoring and Pi Recovery had equal desired/applied
BundleDeployment IDs.

The rollout was interrupted by a network-only outage on rpi1 at about 13:33 UTC.
The OS logging canary continued on the same boot until 13:46 while SSH, API and
exporter connectivity were lost. Independent switch samples showed traffic
from the Pi frozen while traffic toward it advanced, with healthy link/PoE and
no port errors. This supports probable TX stall, not a locally captured driver
fault; the timing does not prove or rule out a Cilium-related trigger.

Pi Recovery initially rejected alerts because its inventory still contained
eight nodes. [PR #192](https://github.com/abhi1693/home-lab/pull/192) added the
independently verified ninth-node binding in encrypted configuration, preserving
credentials and all safety checks. The existing controller confirmed evidence,
cycled only rpi1 at 13:46:22 UTC and verified changed boot ID, retained node UID,
Ready status and exporter recovery at 13:48:22 UTC. No direct cluster or PoE
mutation was used. The retained ledger completed action
`37fde99b-819a-49ff-8470-16328d37dd68` and released its lease.

Rancher's taint-driven Fleet-agent regeneration also interrupted Helm work.
Fleet automatically rolled back and retried the same Git intent, finally
converging without disabling the Cilium taint guard or starting a competing
Helm operation. See the existing incident-coverage runbook for this interaction.

The legacy Ansible validation entrypoint passed the all-node BTF gate but then
failed on missing migrated host artifacts (`/usr/local/bin/cilium` and the old
Traefik manifest); its missing-file message also assumes `stat.path` exists.
That original command is not reported as successful. The validator has since
been corrected to query every deployed Cilium agent and the live Traefik API
resources, without requiring a host Cilium CLI or old bootstrap files. It
retains the BTF, version, rollout, metrics and ingress checks. The original
rollout used direct API, runtime, image, networking and metric evidence; no
bootstrap binary or addon manifest was installed to satisfy the legacy check.

Final post-convergence fixtures from
[PR #191](https://github.com/abhi1693/home-lab/pull/191) and
[PR #193](https://github.com/abhi1693/home-lab/pull/193) passed on all nine nodes
at 14:03 UTC. All final client Pods were created between 13:57:30 and 14:03:02,
after target convergence, with zero restarts. Every client resolved Kubernetes
DNS, reached a ClusterIP backend on a different node, and was blocked from the
explicitly denied 8081 port. Both independent 8081 backend readiness checks
remained healthy. The fixture selected only its own clients and is removed
through Git/Fleet after capture; no production policy was weakened.

Final sampled HTTPS routes for DevFeed, ShipyardHQ, Wardn Hub and DevFeed OIDC
discovery returned HTTP 200. Three native etcd members reported a leader and
exactly one reported itself leader. PostgreSQL was healthy with 3/3 instances;
all 19 attached Longhorn volumes were healthy (nine retained detached volumes
were not activated). No targeted Cilium, Pi Recovery or node-unreachable alert
remained firing. These are bounded rollout observations, not a long-term
performance benchmark or proof that the underlying Pi Ethernet issue is fixed.
