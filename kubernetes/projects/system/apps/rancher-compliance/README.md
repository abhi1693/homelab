# Rancher Compliance

Fleet wrapper for Rancher Compliance in `compliance-operator-system`.

It owns two HelmOps:

- `rancher-compliance-crd`, which installs the Compliance CRDs.
- `rancher-compliance`, which installs the Compliance operator and built-in scan
  profiles.

The install is pinned to chart version `109.2.0+up1.4.3`, matching Kubernetes
`1.35` and Rancher `2.14` chart compatibility. The operator is scheduled only on
ARM64 nodes and uses the chart default scanner images.

Cluster scan definitions are kept in the adjacent `rancher-compliance-scans`
bundle so they can depend on this install.
