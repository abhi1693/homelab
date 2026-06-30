---
title: Fleet Namespace Manifests and PSA Labels
---

# Fleet Namespace Manifests and PSA Labels

Namespace ownership is sensitive in this repository. A bad namespace change can
make Fleet report the namespace as missing or not owned, and namespace deletion
would delete every workload in that namespace. Treat Pod Security Admission
label rollout as a one-namespace-at-a-time change.

This runbook documents the safe pattern validated on the `git-rank` namespace.

## Rules

- Add or change only one namespace per commit.
- Wait for the owning Fleet bundle to become ready before touching the next
  namespace.
- Do not add PSA labels with `kubectl label` or `kubectl annotate` unless the
  user explicitly authorizes a break-glass operation.
- Do not use `namespaceLabels` or `namespaceAnnotations` in `fleet.yaml` for a
  namespace that also has an explicit `Namespace` manifest. Fleet can clobber
  the Helm/ObjectSet ownership metadata and report `namespace.v1 <name> is not
  owned by us`.
- Keep `kube-system`, `longhorn-system`, `cattle-*`, Cilium, monitoring, and
  node-control namespaces out of PSA enforcement during the initial rollout.
- Start with PSA audit/warn labels only unless enforcement is explicitly
  approved for that namespace.

## Safe Pattern

For a normal Fleet app bundle that owns workloads in its target namespace:

1. Add an explicit `namespace.yaml` to the app bundle.
2. Move any existing `namespaceLabels` and `namespaceAnnotations` from
   `fleet.yaml` into `namespace.yaml`.
3. Remove `namespaceLabels` and `namespaceAnnotations` from `fleet.yaml`.
4. Add `helm.takeOwnership: true` to `fleet.yaml`.
5. Add `helm.sh/resource-policy: keep` to the namespace manifest.
6. Add Helm ownership metadata to the namespace manifest.
7. Add PSA labels in warn/audit mode.

Example `fleet.yaml`:

```yaml
---
name: git-rank
defaultNamespace: git-rank
labels:
  app.kubernetes.io/part-of: git-rank
  home-lab.io/project-slug: applications
dependsOn:
  - name: rancher-project-applications
helm:
  takeOwnership: true
```

Example `namespace.yaml`:

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: git-rank
  labels:
    app.kubernetes.io/managed-by: Helm
    app.kubernetes.io/part-of: git-rank
    field.cattle.io/projectId: p-applications
    kubernetes.io/metadata.name: git-rank
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
  annotations:
    field.cattle.io/projectId: local:p-applications
    helm.sh/resource-policy: keep
    meta.helm.sh/release-name: git-rank
    meta.helm.sh/release-namespace: git-rank
```

For `meta.helm.sh/release-name` and `meta.helm.sh/release-namespace`, match the
Fleet Helm release that owns the bundle. For ordinary app bundles this is
usually:

- release name: `fleet.yaml` `name`
- release namespace: `fleet.yaml` `defaultNamespace`

If the namespace manifest is part of a wrapper bundle that deploys into
`fleet-local`, inspect an already-owned resource or existing Helm release before
choosing these values.

## Validation

Run local YAML validation:

```sh
yq eval '.' kubernetes/projects/<project>/apps/<app>/fleet.yaml \
  kubernetes/projects/<project>/apps/<app>/namespace.yaml >/dev/null
```

Run a server-side dry run for the namespace manifest only:

```sh
kubectl apply --dry-run=server \
  -f kubernetes/projects/<project>/apps/<app>/namespace.yaml
```

The dry run may warn that the existing namespace is missing the
`kubectl.kubernetes.io/last-applied-configuration` annotation. That warning is
expected for existing namespaces and does not mutate the cluster during a
server-side dry run.

## Rollout

Commit and push only the namespace-related files:

```sh
git add -- \
  kubernetes/projects/<project>/apps/<app>/fleet.yaml \
  kubernetes/projects/<project>/apps/<app>/namespace.yaml
git commit -m "Add PSA labels for <namespace> namespace"
git push
```

Watch the owning GitRepo and bundle:

```sh
kubectl get gitrepo -n fleet-local home-lab-<project>
kubectl get bundle -n fleet-local <bundle-name>
kubectl get namespace <namespace> -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/audit}{"\n"}{.metadata.labels.pod-security\.kubernetes\.io/warn}{"\n"}'
```

Do not continue to the next namespace until the owning bundle shows `1/1` ready
and the project GitRepo is fully ready.

## Troubleshooting

If Fleet reports:

```text
namespace.v1 <namespace> is not owned by us
```

check for these problems:

- `fleet.yaml` still has `namespaceLabels` or `namespaceAnnotations`.
- The namespace manifest is missing `app.kubernetes.io/managed-by: Helm`.
- The namespace manifest is missing matching `meta.helm.sh/release-name` or
  `meta.helm.sh/release-namespace` annotations.
- The namespace manifest is missing the Rancher project label or annotation.
- The namespace manifest is missing `helm.sh/resource-policy: keep`.

Use read-only inspection:

```sh
kubectl get namespace <namespace> -o json | jq '.metadata.labels, .metadata.annotations'
kubectl get bundle -n fleet-local <bundle-name> -o json | jq '.spec.helm, .status.conditions, .status.summary.nonReadyResources'
kubectl get bundledeployment -A | rg '<bundle-name>|STATUS'
```

If the namespace is already broken, prefer a Git-only fix using the safe pattern
above. Do not patch live metadata unless the user explicitly authorizes a
break-glass operation.

## References

- Rancher Fleet `fleet.yaml` reference: https://fleet.rancher.io/reference/ref-fleet-yaml
- Helm resource policy keep annotation: https://helm.sh/docs/howto/charts_tips_and_tricks/#tell-helm-not-to-uninstall-a-resource
- Rancher Fleet ownership issue context: https://github.com/rancher/fleet/issues/910
