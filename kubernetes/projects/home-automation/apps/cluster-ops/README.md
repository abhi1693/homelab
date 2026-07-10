# Cluster Ops

`cluster-ops` runs generic controllers that observe or operate the home-lab
cluster itself.

## K8s Recommendation Engine

The first runner is `k8s-recommendation-engine-shipyard`. It runs the
recommendation engine in full GitOps proposal mode for the Shipyard profile:

- profile ConfigMap: `shipyard-profile-configmap.yaml`
- state: `k8s-recommendation-engine-shipyard-state`
- Prometheus: `rancher-monitoring-prometheus.cattle-monitoring-system.svc`
- Git worktree: cloned by the init container into `/git/home-lab`
- write mode: commit and push proposals to the `master` branch; Fleet applies
  the resulting desired-state changes
- live workload patching: disabled

To add another profile, add a profile-specific ConfigMap manifest, Deployment,
and PVC, then include them in `kustomization.yaml`. The shared ServiceAccount,
RBAC, namespace, and network policy are reused.
