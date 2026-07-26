# PostgreSQL Operator

This Database project Fleet bundle installs the CloudNativePG operator through
a local wrapper Helm chart.

Current choices:

- Fleet app name: `cnpg-operator`
- Helm release name: `psql`
- chart: local wrapper chart in `chart/`
- upstream dependency: `cloudnative-pg` chart version `0.29.0`
- app version: `1.30.0`
- namespace: `cnpg-system`
- Rancher project: `Database`
- watch scope: cluster-wide
- dashboard: local patched copy of the upstream CloudNativePG dashboard

The operator owns the CNPG CRDs and can reconcile PostgreSQL `Cluster`
resources in application namespaces. Dashboard operator-readiness panels use
available Deployment replicas in the dedicated operator namespace instead of
assuming a particular Helm-generated pod name.
