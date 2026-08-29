# Applications Helm Repositories

This bundle registers Rancher `ClusterRepo` resources used by Applications
project workloads.

It currently owns:

- `harbor` -> `https://helm.goharbor.io`
- `openbao` -> `https://openbao.github.io/openbao-helm`
- `zitadel` -> `oci://ghcr.io/zitadel/zitadel-charts/zitadel`

OCI repositories keep a Git-managed `spec.forceUpdate` timestamp when a
recovered ISP or CoreDNS outage has left Rancher's download condition stuck on
the transient failure. Advance it only after live connectivity is healthy.
