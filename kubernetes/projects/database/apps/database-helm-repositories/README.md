# Database Helm Repositories

This bundle registers Rancher `ClusterRepo` resources used by shared database
infrastructure.

It owns:

- `oci://registry-1.docker.io/bitnamicharts/valkey`
- `https://cloudnative-pg.github.io/charts`

The Bitnami Valkey OCI repository sets `spec.refreshInterval: 900` seconds.
Rancher 2.15.2 otherwise defaults OCI refreshes to
[24 hours](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f0f9ae9d6d356e3b8/pkg/controllers/dashboard/helm/repo_oci.go#L45),
and schedules registry transport errors at that same interval.
The 15-minute policy gives transient download failures regular recovery
attempts through normal reconciliation. Registry connectivity must recover for
the repository to become healthy. HTTP 429 rate-limit backoff remains separate;
the CloudNativePG HTTP repository retains its existing refresh policy.

Changing the interval updates the resource generation, which
[allows an immediate refresh](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f0f9ae9d6d356e3b8/pkg/controllers/dashboard/helm/repo.go#L449)
before the new periodic schedule applies.
