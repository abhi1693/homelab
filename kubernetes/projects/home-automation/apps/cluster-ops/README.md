# Cluster Ops

`cluster-ops` runs generic controllers that observe or operate the home-lab
cluster itself.

## K8s Recommendation Engine

The `k8s-recommendation-engine-controller-manager` Deployment in
`controller-manager.yaml` watches every `ApplicationProfile` resource in
`cluster-ops`. It runs the recommendation engine in full GitOps proposal mode
for every profile:

- CRD bundle: `../cluster-ops-crds`
- Literal-manifest production profiles: `finance-profile.yaml`,
  `git-rank-profile.yaml`, `indexly-profile.yaml`,
  `media-metube-profile.yaml`, `media-storage-profile.yaml`,
  `personal-blog-profile.yaml`, `portfolio-profile.yaml`,
  `qbittorrent-smart-queues-profile.yaml`, and `rack-ops-profile.yaml`
- Helm-values production profiles: `cnpg-system-profile.yaml`,
  `harbor-profile.yaml`, `media-helm-profile.yaml`, `netbox-profile.yaml`, and
  `zitadel-profile.yaml`; their chart-specific replica and resource keys are
  declared with `helmValues.paths`
- All production-baselined profiles start with scaling and recovery disabled
  while they accumulate stable learning history
- Shipyard profile: `shipyard-profile.yaml`
- Wardn Hub profile: `wardn-hub-profile.yaml`; it learns from all seven live
  production Deployments with scaling disabled during baseline onboarding
- shared state manifest: `controller-state-pvc.yaml`
- compatibility state identifiers: the bound PVC remains
  `k8s-recommendation-engine-shipyard-state` and the SQLite file remains
  `shipyard.db` until a separate offline migration can rename them without
  resetting accumulated recommendation history
- Prometheus: `rancher-monitoring-prometheus.cattle-monitoring-system.svc`
- Git worktree: cloned by the init container into `/git/home-lab`
- write mode: commit and push proposals to the `master` branch; Fleet applies
  the resulting desired-state changes
- live resource patching: disabled
- failed-Pod recovery: enabled for the Shipyard web workload, limited by the
  profile cooldown/attempt budget and a Pod-delete Role in `shipyardhq`

To add another profile, add an `ApplicationProfile` manifest and include it in
`kustomization.yaml`. The controller Deployment, state PVC, ServiceAccount,
RBAC, namespace, and network policy are shared by all profiles.

For Helm-rendered Deployments, `sourceFile` points at the effective Git values
file and `helmValues.paths` maps replicas, CPU request, and memory request to
existing scalar keys. The 15 chart-backed workloads onboarded here were checked
against the live production Deployment and the exact chart version. Four media
charts now declare their previously implicit `workload.main.replicas: 1` so the
replica source remains an explicit, patchable scalar without changing runtime
behavior.

NetBox also loads a later Secret-backed values source. Its current keys do not
overlap the six mapped replica/resource paths; adding such an override there
would make `values.yaml` non-authoritative and must be treated as source drift.

The current exclusions are intentional:

- `git-rank`, `indexly`, `finance`, `personal-blog`, `portfolio`, the Rack Ops
  controller, MeTube, media library keeper, and qBittorrent smart queues already
  use literal-manifest profiles and must not get duplicate Helm owners
- Home Assistant, UPS, Harbor registry, Dispatcharr, and Profilarr have multiple
  regular containers; the engine cannot yet select an independently mapped
  container
- Valkey, Harbor Trivy, and Jellyseerr are StatefulSets; Rack Ops node agents are
  DaemonSets; batch jobs and CronJobs are also outside the Deployment-only model
- PostgreSQL renders a CloudNativePG `Cluster`; its Pooler Deployments are
  operator-owned and their writable values are nested in YAML sequences, which
  the mapping model deliberately does not traverse
- Ryokan, Shoko, and Dispatcharr are scaled to zero and do not provide a useful
  active production learning baseline
- Home Assistant also stores chart values inside `HelmChart.spec.valuesContent`,
  an embedded block scalar that cannot be safely patched as a standalone values
  document
