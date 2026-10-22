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
- dashboard: local patched snapshot of upstream `main` at
  [`47e4c51219fdbb3c7ef2c4d91a2d8855e9ca1880`](https://github.com/cloudnative-pg/grafana-dashboards/commit/47e4c51219fdbb3c7ef2c4d91a2d8855e9ca1880)

The operator owns the CNPG CRDs and can reconcile PostgreSQL `Cluster`
resources in application namespaces. Dashboard operator-readiness panels use
available Deployment replicas in the dedicated operator namespace instead of
assuming a particular Helm-generated pod name.

## Dashboard refreshes

Refresh `chart/files/cnp.json` from the default branch (`main`) of
[`cloudnative-pg/grafana-dashboards`](https://github.com/cloudnative-pg/grafana-dashboards),
using `charts/cluster/grafana-dashboard.json`. Record the exact source commit
above so each vendored snapshot is reproducible; the dashboard is not fetched
at runtime and does not depend on the published dashboard chart tag.

Preserve the local memory-query job selector (`kubelet|k3s-server`) and the
operator-readiness queries based on Deployment availability. The current
snapshot includes upstream WAL idle-state handling, native/Barman-plugin backup
metric support, checkpoint rates, transaction rate intervals, and
`maintenance_work_mem` unit fixes. Keep future refreshes scoped to this JSON
and its documented provenance, then render and validate the wrapper chart
before letting Fleet reconcile it.
