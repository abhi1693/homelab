# Cluster Ops

`cluster-ops` runs generic controllers that observe or operate the home-lab
cluster itself.

Its custom Deployment retains two ReplicaSet revisions; Git and Fleet history
remain the primary rollback path.

## K8s Recommendation Engine

The `k8s-recommendation-engine-controller-manager` Deployment in
`controller-manager.yaml` watches every `ApplicationProfile` resource in
`cluster-ops`. It runs the recommendation engine in full GitOps proposal mode
for every profile:

- CRD bundle: `../cluster-ops-crds`
- Literal-manifest production profiles: `finance-profile.yaml`,
  `media-anime-profile.yaml`, `personal-blog-profile.yaml`,
  `portfolio-profile.yaml`,
  `qbittorrent-smart-queues-profile.yaml`, and `rack-ops-profile.yaml`
- Helm-values production profiles: `cnpg-system-profile.yaml`,
  `harbor-profile.yaml`, `media-helm-profile.yaml`, `openbao-profile.yaml`,
  `valkey-profile.yaml`, and `zitadel-profile.yaml`;
  their chart-specific replica and resource keys are declared with
  `helmValues.paths`
- Production profiles generally run with replica, CPU-request, and
  memory-request management enabled; persisted learning history still feeds
  the stability and safety gates before Git proposals are committed
- The Ryokan and Shoko workloads in `media-anime-profile.yaml` start in
  observe-only mode because their initial baseline includes first-run setup and
  Shoko library scanning. The profile records resource history every five
  minutes, but all scaling dimensions remain disabled until normal idle and
  scan cycles have been observed; their single-replica count stays
  operator-managed
- Managed CPU and memory requests use a 5 percent minimum material-change gate
  with a 10 percent maximum decrease per proposal. Keeping the minimum below
  the decrease bound prevents quantity rounding from suppressing every
  conservative downsize step
- Literal-manifest profiles keep memory limits in the workload manifests; keep
  those limits above the recommendation headroom because the engine currently
  adjusts memory requests, not paired memory limits
- Shipyard profile: `shipyard-profile.yaml`
- Wardn Hub profile: `wardn-hub-profile.yaml`; all five live production
  Deployments, including the consolidated application worker, run with scaling
  enabled
- shared state manifest: `controller-state-pvc.yaml`
- compatibility state identifiers: the bound PVC remains
  `k8s-recommendation-engine-shipyard-state` and the SQLite file remains
  `shipyard.db` until a separate offline migration can rename them without
  resetting accumulated recommendation history
- Prometheus: `rancher-monitoring-prometheus.cattle-monitoring-system.svc`
- Git worktree: cloned by the init container into `/git/home-lab`
- Git clone init resources: `25m`/`64Mi` requests with `250m`/`192Mi`
  limits, preventing proposal setup from running as BestEffort
- write mode: commit and push proposals to the `master` branch; Fleet applies
  the resulting desired-state changes
- rollout verification: after a pushed proposal, wait for the affected Fleet
  GitRepo and bundle to return ready and verify the changed Deployment or
  StatefulSet rollout; Helm-backed profiles can remain `WaitApplied` while
  chart hooks and pods converge
- proposal status: `ProposalReady` reports Git proposal eligibility separately
  from the workload-health `Ready` condition
- reconcile timeout: five minutes, allowing full profile collection and Git
  proposal work to finish during transiently slow API or Prometheus responses
- persisted state retention: 14 days (`336h`); expired observations and
  operational history are pruned at most once per hour
- leader election: disabled because this is a single-replica `Recreate`
  Deployment, avoiding unnecessary exits when the API server is briefly
  unavailable
- live resource patching: disabled
- failed-Pod recovery: enabled for the Shipyard web workload, limited by the
  profile cooldown/attempt budget and a Pod-delete Role in `shipyardhq`

To add another profile, add an `ApplicationProfile` manifest and include it in
`kustomization.yaml`. The controller Deployment, state PVC, ServiceAccount,
RBAC, namespace, and network policy are shared by all profiles.

For Helm-rendered Deployments and StatefulSets, `sourceFile` points at the
effective Git values file and `helmValues.paths` maps replicas, CPU request, and
memory request to existing scalar keys. The chart-backed workloads onboarded
here were checked against the live production workload and the exact chart
version. Four media charts now declare their previously implicit
`workload.main.replicas: 1` so the replica source remains an explicit,
patchable scalar without changing runtime behavior.

The NetBox recommendation profile is omitted while the web and worker
Deployments are paused at zero replicas. Restore and revalidate the profile
only after restoring the NetBox workloads; otherwise it could propose a
scale-up and a suspended profile would keep Fleet reporting the bundle as
progressing.

Valkey uses the multi-container selector support in `vars.container` to manage
only the `valkey` data container request paths under `replica.resources`.
Sentinel and metrics sidecar requests, plus all memory limits, remain manually
managed in `values.yaml`.

The current exclusions are intentional:

- `finance`, `personal-blog`, `portfolio`, the Rack Ops controller, media
  library keeper, and qBittorrent smart queues already
  use literal-manifest profiles and must not get duplicate Helm owners
- Home Assistant, UPS, Harbor registry, Loki,
  Alertmanager, and Prometheus have multiple regular containers without a
  selected profile container or operator-owned workload shapes; the engine
  cannot patch their upstream custom resource safely
- Rack Ops node agents are DaemonSets; batch jobs and CronJobs are also outside
  the profile target model
- PostgreSQL renders a CloudNativePG `Cluster`; its Pooler Deployments are
  operator-owned and their writable values are nested in YAML sequences, which
  the mapping model deliberately does not traverse
- Home Assistant also stores chart values inside `HelmChart.spec.valuesContent`,
  an embedded block scalar that cannot be safely patched as a standalone values
  document
