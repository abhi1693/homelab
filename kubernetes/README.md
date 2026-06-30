# Kubernetes Desired State

This directory owns resources that are applied to the running K3s cluster after
the infrastructure bootstrap has completed.

Rancher Fleet reconciles app manifests from this directory after the
`fleet_apps` Ansible role has bootstrapped the Fleet `GitRepo`.

Project-scoped apps are managed by project-specific Fleet `GitRepo` resources.
Each project GitRepo lists app directories explicitly so Fleet ImageScan can
write image updates back to the matching files.

Rancher project metadata bundles are tracked separately from
`kubernetes/projects/*/_project` by `home-lab-rancher-projects` because Rancher
`Project` resources are not safe to replace during drift correction.

Fleet control-plane bundles are managed by `home-lab-fleet` from
`kubernetes/fleet/*`.

For day-to-day app changes:

1. Edit files under the owning project path, such as
   `kubernetes/projects/applications/apps/<app>/`.
2. Commit and push to the configured Fleet branch.
3. Let Fleet reconcile the app bundle.

K3s `HelmChart` resources should live in `kube-system`; their
`targetNamespace` controls where the chart itself is installed.

For upstream Helm charts, prefer a Fleet `HelmOp` resource managed by a small
GitOps wrapper bundle. Keep chart values in Git and generate a ConfigMap from
the local `values.yaml` when the HelmOp needs `valuesFrom`.

## Fleet ImageScan

Fleet ImageScan is enabled through the Rancher bootstrap values in
`infrastructure/ansible` and project GitRepos that can own app image updates set
`imageScanInterval` plus `imageScanCommit`.

Workloads pull private Harbor project images from `registry.home/<project>/...`
with a namespace-scoped `harbor-registry` dockerconfigjson Secret. Each
namespace has one Harbor robot account named `robot-namespace-<namespace>` with
pull access across local Harbor repositories, and the Secret contains a single
`registry.home` auth entry for that robot. Fleet ImageScan must scan the local
Harbor repository, not the upstream source registry, and use the `:tag` marker
form in workload manifests so Fleet updates only the tag while the deployed
image stays on
`registry.home`. Public proxy-cache projects such as
`registry.home/docker.io` and `registry.home/ghcr.io` stay public and do not
need workload image pull Secrets. The older `ghcr-home-lab` Secret remains only
for direct GHCR pulls such as Harbor bootstrap images.

Do not attach ImageScan directly to SHA-only tags such as `sha-<git-sha>` or
`master-<git-sha>`. Fleet selects tags by semver or alphabetical ordering, and
commit hashes are not time-ordered. App image pipelines should publish semver
tags from GitHub releases, for example `0.3.2` from release tag `v0.3.2`, before
the bundle is wired to an ImageScan semver policy. For digest-pinned mutable
tags, use a controlled tag set and annotate the field with the `:digest`
replacement form.

Example bundle wiring:

```yaml
imageScans:
  - image: registry.home/example-project/example-app
    tagName: example-app
    interval: 1h0m0s
    secretRef:
      name: harbor-registry
    policy:
      semver:
        range: ">=0.0.0"
```

```yaml
image: registry.home/example-project/example-app:0.1.0 # {"$imagescan": "example-app"}
```

See the Fleet ImageScan documentation for the supported `fleet.yaml` and
manifest annotation forms:
https://fleet.rancher.io/how-tos-for-users/imagescan
