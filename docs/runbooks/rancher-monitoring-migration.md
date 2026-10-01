---
title: Rancher Monitoring to Upstream Prometheus Migration
---

# Rancher Monitoring to Upstream Prometheus Migration

## Status and scope

The preparation stage was deployed through Fleet on 2026-10-01, in commits
`71b48289` and `aef22f70`. All 23 system bundles became Ready, and monitoring
Helm revision 72 records both retention annotations. The before/after inventory
comparison passed, both native write destinations were reachable, and Thanos
returned a historical query from 24 hours earlier. The legacy runtime at that checkpoint was `rancher-monitoring`
`109.0.5+up80.9.1-rancher.19`. The follow-up preparation commit `6fdccbd6`
retained 32 dashboard ConfigMaps and all three Rancher bridge Services, and
enabled a 30-minute OTLP ordering window. Fleet reconciled all 23 system bundles
and Helm revision 73 before chart replacement. These are dated checkpoints;
repeat live observations before advancing.

On 2026-10-01 the operator explicitly authorized this monitoring cutover without
new backups because UNAS cannot provide NFSv4. This exception applies only to
this cutover. Preserve every existing PVC/PV binding and keep Grafana 12.3.1,
Prometheus 3.8.1, and Alertmanager 0.30.0 during the chart handoff. No data loss
is expected, but there is no current storage recovery copy if data is damaged.
The temporary `longhorn_backups` UNAS share is not configured as a backup target.

The following conditions were identified during preparation:

- Neither active Prometheus Longhorn volume had a registered backup or a
  `lastBackup`/`lastBackupAt` value. A verified storage recovery copy, including
  Grafana's database, is normally required; the operator waived that gate for
  this cutover. Inventory snapshots are not storage backups.
- Prometheus reported out-of-order OTLP `target_info` samples for DevFeed worker
  services. Collector logs show permanent HTTP 400 responses and dropped
  batches both before preparation (for example 07:37 UTC) and afterward
  (07:42–07:43 UTC). Both destinations continue receiving metrics and exporter
  queues were empty, but ingestion was not lossless. Preparation revision 73
  enabled `outOfOrderTimeWindow: 30m`; both exporters then reported zero failed
  points over five minutes and empty queues before runtime cutover. Keep
  observing ingestion after the handoff. The separate DevFeed producer identity
  fix remains pending its application release; the ordering window does not
  replace unique service instance identities. A passing inventory comparison
  does not validate OTLP delivery.

The destination is upstream `prometheus-community/kube-prometheus-stack`, the
existing two-replica Thanos query layer, and Rancher's maintained
`rancher-monitoring-dashboards` integration. Loki, Tempo, Pyroscope, Alloy,
OpenTelemetry, custom dashboards, rules, and automation remain part of the
observability system. Preserve the `prometheus`, `alertmanager`, `loki`, `tempo`,
and `pyroscope` datasource UIDs.

The initial cutover selects upstream chart `80.9.1` (operator `v0.87.1`),
matching the legacy chart's base, fetched from the official GHCR OCI repository,
and dashboard chart `110.0.1+up0.1.4`.
Prometheus 3.8.1, Grafana 12.3.1 and Alertmanager 0.30.0 retain their exact
stateful images. The newer chart `91.8.2` is deferred because it combines
operator and Grafana upgrades with the ownership change. The rendered runtime,
CRD hook and dashboard proxy images have ARM64 manifests.

All cluster changes go through Fleet. Do not uninstall monitoring, delete its
CRDs, recreate its namespaces, or run a manual Helm upgrade as part of this
runbook. The namespace ownership policy in
[fleet-namespace-psa-labels.md](fleet-namespace-psa-labels.md) remains in force.

## Preparation stage

The first Git change:

1. Adds `helm.sh/resource-policy: keep` to the existing Prometheus and
   Alertmanager custom resources. Their existing PVC retention policies and
   explicitly retained PVCs remain in effect. This annotation must be present
   in an applied Helm revision before a subsequent revision drops the objects.
   It does not protect against CRD deletion or namespace deletion.
2. Changes `prometheus-write-0` and `prometheus-write-1` to the existing native
   `http-web` container port (9090), bypassing Rancher's NGINX sidecar. Service
   names, replica selectors, OTLP URLs, and resource attribute promotion stay
   stable. The telemetry processors allow TCP/9090 alongside the old TCP/8081
   route so rollback remains possible.
3. Registers the `prometheus-community` ClusterRepo.
4. Adds `scripts/monitoring-migration-state.py` for private snapshots and
   read-only comparisons.

The monitoring wrapper includes an additive `prometheus-native-write`
NetworkPolicy selecting only telemetry processors and permitting only their
Prometheus peers on TCP/9090. This is necessary because the separate telemetry
bundle depends on monitoring readiness and otherwise cannot admit the new port
until the monitoring Helm upgrade finishes. The policy travels with the write
Services. Existing retry/queue configuration covers bounded endpoint convergence;
inspect both exporters and queues after rollout. Do not advance if retries
persist or either destination stops receiving metric points.

## Capture the baseline

Use the intended kubeconfig context. The snapshot command makes only GET
requests. It exports dashboard definitions visible to Grafana's current Viewer
identity, datasource identities, labeled dashboard ConfigMaps, Alertmanager
silences, monitoring custom resource specifications, namespace/PVC identities,
workload readiness, and target/rule inventory from each Prometheus replica.

```sh
python scripts/monitoring-migration-state.py snapshot \
  --output ~/.local/state/home-lab/monitoring-migration/before.json
```

Snapshots are mode 0600, cannot overwrite existing files, and must be outside
the repository. They contain private dashboard content. The script does not
read Kubernetes Secrets or Helm values. It uses `http://grafana.home` by
default; `--grafana-url` selects a different reachable URL. Authentication or
API failures fail the capture rather than silently skipping data. If Grafana
gains multiple organizations, export each organization's dashboards separately.

This snapshot is an inventory and dashboard export, **not a storage backup**.
The initial snapshot contained 72 dashboards visible in Grafana and 73 JSON
documents in labeled ConfigMaps. The additional `Node Exporter / AIX` document
was already absent from Grafana's search results; retain its ConfigMap document
in the baseline rather than counting that existing discrepancy as a migration
regression.

Normally, before runtime cutover, additionally verify recoverable Prometheus volume
backups and a consistent Grafana database copy, together with its encryption
key/configuration and SOPS-managed credentials. Preserve Alertmanager data and
silences. Do not point two Prometheus processes at the same TSDB or start two
Grafana processes against the existing SQLite file.

## Validate the preparation change

Render the pinned legacy chart with the updated values into a private temporary
directory and confirm that both custom resources have the keep annotation.
Render the Kustomize wrapper and validate the changed Kubernetes manifests
with server-side dry runs. Dry runs must include `--dry-run=server`.

After the authorized commit/push and Fleet reconciliation:

```sh
kubectl -n fleet-local get gitrepo home-lab-system
kubectl -n fleet-local get helmop rancher-monitoring-stack rancher-monitoring-crd
kubectl -n cattle-monitoring-system get prometheus,alertmanager,statefulset
python scripts/monitoring-migration-state.py snapshot \
  --output ~/.local/state/home-lab/monitoring-migration/prepared.json
python scripts/monitoring-migration-state.py compare \
  ~/.local/state/home-lab/monitoring-migration/before.json \
  ~/.local/state/home-lab/monitoring-migration/prepared.json \
  --require-prepared
```

The comparison requires the same cluster, namespace/PVC identities and volume
bindings, retained Prometheus/Alertmanager identities, monitoring object names,
dashboard/datasource UIDs, rule coverage, healthy targets/rules, and ready
monitoring workloads. `--require-prepared` additionally checks both keep
annotations, native write ports, processor egress, and the upstream repository.
It conservatively flags reduced target counts; investigate legitimate workload
scaling rather than suppressing a failed comparison.

Also confirm:

- Fleet's desired/applied commit matches the pushed preparation commit and
  affected bundles are Ready.
- The applied Helm manifest contains both keep annotations; live metadata alone
  is insufficient evidence of Helm's recorded removal behavior.
- Both processor metrics exporters send points, queues drain, and no new
  sustained export failures appear. Observe for at least ten minutes.
- Existing Grafana dashboards, Thanos queries, and rack/Home Assistant consumers
  continue working. Compare a historical query from before the change.

## Runtime handoff

1. Upgrade the existing `rancher-monitoring-crd` release in place to upstream
   `kube-prometheus-stack` `80.9.1`, with only CRDs and their upgrade Job enabled.
   The old chart's **pre-delete hook deletes all monitoring CRDs** after waiting
   for the Rancher App to disappear. Never uninstall it. An in-place chart
   upgrade replaces that hook without invoking it. The upstream Job uses
   server-side apply and takes field ownership of schemas. The matching operator
   version avoids combining the handoff with a schema version upgrade.
2. Upgrade the existing `rancher-monitoring` release in place to the same
   upstream chart. Keep `nameOverride`/`fullnameOverride`, Prometheus and
   Alertmanager CR names, service accounts, claim template names and all PVC/PV
   bindings. Keep the Grafana Deployment name, Recreate strategy, single replica
   and existing claim. The operator also uses Recreate to avoid overlapping
   reconciliation. No storage copies, PVC replacement or runtime data-format
   upgrades are part of this change.
3. Create native backend Services `monitoring-prometheus`,
   `monitoring-alertmanager` and `monitoring-grafana`. Prometheus alerts and
   Grafana's Alertmanager datasource use the native Alertmanager Service.
   Grafana's ingress targets the native Grafana Service. Thanos and the two
   ordinal OTLP write Services keep their existing identities.
4. Reconcile the separate `rancher-monitoring-dashboards` release after the
   runtime dependency. It adopts the retained Rancher UI bridge Services and
   eight integration dashboard ConfigMaps. Its two proxy replicas target the
   distinct native backend Services. Rancher UI access can briefly interrupt
   during this handoff; Grafana's direct ingress is independent of those proxies.
5. `preserved-dashboards-values.yaml` retains 25 public chart ConfigMaps with
   their original namespace, names and UIDs under the runtime release. Default
   upstream dashboard generation is disabled to prevent duplicate UIDs in a
   second namespace. Review these preserved definitions during future chart
   upgrades. The dashboard integration chart owns its own maintained definitions;
   custom app and UI dashboard storage stays in place.
6. Native HTTPS kubelet scraping replaces the 24 PushProx paths across eight
   nodes. Preserve `job=k3s-server`, `metrics_path`, cluster identity labels,
   cAdvisor and probe collection, and the API-server duplicate filter. The
   dedicated API server scrape retains the SLI histogram. The old two K3s
   ServiceMonitors are replaced by `rancher-monitoring-kubelet`; compare endpoint
   coverage and health rather than requiring their old object names.
7. Remove the unused Prometheus Adapter: no HPAs existed at handoff and its only
   custom metric rule intentionally matched no series. Keep cluster-wide monitor,
   rule and AlertmanagerConfig selectors, Slack routing, exporter textfiles,
   namespace label exports, tolerations and resource bounds. In particular, node
   exporter must tolerate both NoSchedule and NoExecute to cover all eight nodes.

Namespaces remain owned by the existing wrapper manifests. The HelmOps no longer
set `namespaceLabels` or `namespaceAnnotations`, which otherwise overwrite
namespace ownership metadata. No namespace is deleted or recreated.

After Fleet reconciliation, capture a new private inventory. Require unchanged
namespace/CR/PVC UIDs and PV bindings; all 72 baseline Grafana dashboard UIDs and
five datasource UIDs; all baseline rule names; healthy native K3s endpoints and
both Prometheus replicas; both Alertmanager replicas; historical Thanos queries;
and no sustained OTLP export failures. Inspect any strict comparison failure:
the deliberate two-to-one K3s ServiceMonitor replacement is an equivalence, not
lost coverage. Keep the unmodified comparison output with the private snapshot.
Observe both OTLP exporters for ten minutes. Do not send a notification test
without authorization.

## Handoff observations (2026-10-01)

The runtime was replaced in place by commit `6dfc9dc2`, followed by control-plane
node exporter toleration and HelmOp OCI reference fixes in `61a07bdc` and
`5187c1e6`. Fleet HelmOps use the complete OCI reference in `helm.repo`, with no
`helm.chart`; the fleet.yaml chart-reference syntax is not interchangeable.
The CRD and runtime releases reached revisions 8 and 79 respectively.

During the first dashboard install, the old runtime's drift correction and
resource cleanup overlapped the new release's adoption. Its proxy Deployment
became ready, but some shared resources were reverted or removed and the first
Helm install remained pending until its 20-minute timeout. Fleet retried it
successfully at 08:40 UTC: dashboard release revision 2 became deployed, the
three bridge endpoints responded, and all 23 system bundles became Ready.
Native Grafana ingress and the new backend Services stayed independent of the
bridge. For a future handoff, finish the
runtime upgrade and ownership release in one reconciled Git stage before adding
the dashboard HelmOp in a separate commit. A dependency on an existing Ready
bundle alone does not serialize that bundle's next revision.

The first post-cutover inventory retained all baseline namespace, Prometheus,
Alertmanager and PVC UIDs and volume bindings; all 72 Grafana dashboard UIDs;
all five datasource UIDs/types; and all 332 distinct rule names on both replicas.
After the bridge retry Grafana listed 80 dashboards: the baseline 72, an
already-provisioned AIX dashboard now visible after reload, and seven additional
integration dashboards (two etcd, two NGINX, two logging, one backup).
In chart `110.0.1+up0.1.4`, `dashboardArtifacts.groups`
controls the Rancher dashboard index; the individual ConfigMap templates still
render the optional NGINX, logging and backup dashboards.
The conservative comparison also flags the removed empty
`rancher-monitoring-kubernetes-system-controller-manager` PrometheusRule, which
contained a group without any rules, and the intentional replacement of the
two K3s ServiceMonitors. These are not lost rule or scrape coverage.

A query through Grafana's Prometheus datasource (Thanos) returned 175 `up`
series at a timestamp 24 hours before the check. Both active Prometheus Longhorn
volumes were attached and healthy with three replicas. Inventory snapshots are
private local evidence, not storage backups.

At 08:36 UTC both OTLP exporters reported zero failed metric points over ten
minutes, empty queues, and approximately 156 metric points per second each.
Both collector logs had no export errors after 08:25:30 UTC. Earlier connection
retries during the Prometheus rollout drained successfully. The producer
identity follow-up described above remains separate from this cutover.

Final runtime observations at 08:42 UTC: both Prometheus replicas had 179
healthy targets and 370 healthy rule evaluations (332 distinct names). This
includes 24 HTTPS K3s paths across all eight nodes and eight node exporters.
Prometheus and Alertmanager each had two ready replicas, Grafana had one, and
the integration proxy had two. All three monitoring HelmOps were Ready. The
ten-minute OTLP failure counters and queues remained zero, and both Longhorn
volumes remained healthy. Grafana's direct ingress reported its database OK;
all three Rancher bridge APIs responded successfully.

## Rollback

For this preparation stage, revert the Git change and reconcile through Fleet.
TCP/8081 remains allowed while the Services return to `nginx-http`. No data
format, runtime image, CRD schema, or storage binding changes in this stage.

For this cutover, the stateful runtime versions and volumes remain unchanged.
Keep `values.yaml` and `crd-values.yaml` as the legacy configuration reference.
A rollback must first disable the dashboard chart's three proxies before
returning their Service ownership to the runtime release; do not allow both
releases to reconcile the same Services. Roll back the runtime through Fleet
with the same stateful images and claims. Keep upstream CRD management in place
unless a separately reviewed schema rollback is needed. Never uninstall either
CRD release or downgrade a data directory speculatively. The backup exception
means rollback cannot recover damaged storage.

## References

- [Fleet HelmOps chart references](https://fleet.rancher.io/how-tos-for-users/helm-ops)
- [Rancher monitoring migration](https://documentation.suse.com/en-us/cloudnative/rancher-manager/v2.15/en/observability/monitoring-and-dashboards/monitoring-and-dashboards.html)
- [Upstream chart upgrade guide](https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-91.8.2/charts/kube-prometheus-stack/UPGRADE.md)
- [K3s metrics and duplicate collection](https://docs.k3s.io/reference/metrics)
- [Helm resource retention](https://helm.sh/docs/howto/charts_tips_and_tricks/#tell-helm-not-to-uninstall-a-resource)
