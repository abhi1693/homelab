# PostgreSQL Operator

This Database project Fleet bundle installs the CloudNativePG operator through
a local wrapper Helm chart.

Current choices:

- Fleet app name: `cnpg-operator`
- Helm release name: `psql`
- chart: local wrapper chart in `chart/`
- upstream dependency: `cloudnative-pg` chart version `0.28.2`
- app version: `1.29.1`
- namespace: `cnpg-system`
- Rancher project: `Database`
- watch scope: cluster-wide
- dashboard: local patched copy of the upstream CloudNativePG dashboard

The operator owns the CNPG CRDs and can reconcile PostgreSQL `Cluster`
resources in application namespaces.
