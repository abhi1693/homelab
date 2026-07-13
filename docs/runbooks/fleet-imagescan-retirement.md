---
title: Retire Orphaned Fleet ImageScans
---

# Retire Orphaned Fleet ImageScans

## Meaning

Fleet ImageScan is disabled because Renovate owns container image updates. If
the Rancher Helm values omit the nested Fleet configuration, Rancher can retain
older Fleet release overrides and leave ImageScan active.

Absent image overrides are rendered as `null` deletion markers. Rancher uses
those markers to remove older release overrides, after which the Fleet chart
selects its own default controller and agent images.

On 2026-07-13, the cluster had 62 orphaned `ImageScan` resources in
`fleet-local`. Twelve were stalled. All 62 referred to commits from before the
Fleet-to-Renovate migration, had no owner references or finalizers, and were no
longer declared by the current GitRepos.

## Impact

The orphaned resources cause repeated Fleet controller errors and unnecessary
reconciliation. Existing application traffic is not interrupted, but the event
and log noise can hide new failures.

## Diagnosis

Confirm the Rancher-managed Fleet values disable ImageScan:

```sh
helm -n cattle-system get values rancher --all
helm -n cattle-fleet-system get values fleet --all
```

The Rancher values must include nested `imagescan.enabled: false`. The Fleet
controller and GitJob deployments must omit `IMAGESCAN_ENABLED`; Fleet does not
render that environment variable when ImageScan is disabled:

```sh
kubectl -n cattle-fleet-system get deployment fleet-controller \
  -o 'jsonpath={.spec.template.spec.containers[?(@.name=="fleet-controller")].env[?(@.name=="IMAGESCAN_ENABLED")].value}{"\n"}'
kubectl -n cattle-fleet-system get deployment gitjob \
  -o 'jsonpath={.spec.template.spec.containers[?(@.name=="gitjob")].env[?(@.name=="IMAGESCAN_ENABLED")].value}{"\n"}'
```

Both commands must print blank lines. List the cleanup candidates and inspect
their ownership metadata before deleting anything:

```sh
kubectl -n fleet-local get imagescans.fleet.cattle.io \
  -l 'app.kubernetes.io/managed-by=Helm,fleet.cattle.io/repo-name'
kubectl -n fleet-local get imagescans.fleet.cattle.io \
  -l 'app.kubernetes.io/managed-by=Helm,fleet.cattle.io/repo-name' \
  -o json | jq '[.items[] | {
    name: .metadata.name,
    finalizers: (.metadata.finalizers // []),
    owners: (.metadata.ownerReferences // [])
  }]'
```

Stop if any candidate has an owner reference or finalizer. Do not patch away a
finalizer or force-delete the resource.

## Mitigation

First apply the Rancher role. Use the diagnosis commands above and wait until
the Fleet controller, GitJob, HelmOps, and local Fleet agent have completed
their rollouts using the current Rancher chart defaults. Run the role's full
validation entrypoint after the orphan cleanup because it also asserts that no
ImageScans remain.

Deleting live resources is a break-glass operation and requires explicit user
authorization in the current session. After authorization, save a backup and
delete only the previously inspected selector:

```sh
kubectl -n fleet-local get imagescans.fleet.cattle.io \
  -l 'app.kubernetes.io/managed-by=Helm,fleet.cattle.io/repo-name' \
  -o yaml > /tmp/fleet-orphaned-imagescans.yaml

kubectl -n fleet-local delete imagescans.fleet.cattle.io \
  -l 'app.kubernetes.io/managed-by=Helm,fleet.cattle.io/repo-name' \
  --wait=true \
  --timeout=120s
```

## Verification

Confirm no ImageScans remain and that the Fleet rollouts are healthy:

```sh
kubectl get imagescans.fleet.cattle.io --all-namespaces -o name
kubectl -n cattle-fleet-system rollout status deployment/fleet-controller
kubectl -n cattle-fleet-system rollout status deployment/gitjob
kubectl -n cattle-fleet-system rollout status deployment/helmops
kubectl -n cattle-fleet-local-system rollout status deployment/fleet-agent
```

The first command must return no output. Recheck it after the GitRepos reconcile
to prove that the retired resources are not recreated.

## Rollback

Do not restore the backup while ImageScan remains disabled. If ImageScan is
intentionally re-enabled in a future change, restore only resources that are
again declared by the matching GitRepo and pass a server-side dry run first.
