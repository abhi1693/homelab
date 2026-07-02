# System Project

The System project owns cluster services that support every other project:
monitoring, logging, tracing, profiling, backup, DNS, compliance, secret
operators, and maintenance controllers.

Fleet tracks this project through the `home-lab-system` GitRepo. The Rancher
`System` project is built in, so workloads here keep their namespaces assigned
to the existing Rancher system project.

## Why This Project Exists

System services are shared dependencies. They should not be hidden inside app
projects because failures here affect the whole cluster. Keeping them together
makes it easier to reason about observability, backup, compliance, DNS, and
operator lifecycle.

## App Catalog

| App | What it does | Why it matters |
| --- | --- | --- |
| `system-helm-repositories` | Registers system chart repositories. | Makes Rancher, Jetstack, ExternalDNS, and related charts available. |
| `rancher-monitoring` | Prometheus, Grafana, Alertmanager, dashboards, and rules. | Primary metrics, dashboards, and alerting plane. |
| `alloy-logs` | Log collection pipeline. | Sends cluster/app logs toward Loki. |
| `loki` | Log backend. | Stores and queries logs. |
| `tempo` | Trace backend. | Stores OpenTelemetry traces and exposes trace query APIs. |
| `pyroscope` | Profiling backend. | Supports continuous profiling experiments. |
| `opentelemetry-collector` | OTLP receiver and forwarding layer. | Gives apps one local metrics/traces endpoint. |
| `alloy-faro` | Frontend telemetry support. | Supports browser/app telemetry collection. |
| `external-dns-unifi` | Reconciles internal DNS records from Ingress hosts. | Keeps `*.home` DNS aligned with Traefik ingress. |
| `external-dns-unifi-networkpolicy` | Network boundary for ExternalDNS. | Limits provider and Kubernetes access paths. |
| `sops-secrets-operator` | Converts SOPS encrypted resources into native Secrets. | Lets Fleet apply encrypted secret manifests safely. |
| `cert-manager-secrets` | Secret bundle for DNS01 credentials. | Supplies cert-manager provider credentials. |
| `rancher-backup` | Rancher Backup CRDs and operator. | Backs up Rancher state to object storage. |
| `rancher-backup-secrets` | Backup credential bundle. | Provides object-store credentials through SOPS. |
| `rancher-compliance` | Rancher Compliance CRDs and operator. | Provides CIS scan capability. |
| `rancher-compliance-scans` | One-time and scheduled scan definitions. | Keeps compliance scan cadence in Git. |
| `descheduler` | Periodic workload rebalancing. | Moves safe workloads away from overloaded nodes. |
| `longhorn-recurring-jobs` | Recurring Longhorn jobs such as filesystem trim. | Handles storage maintenance policy. |
| `longhorn-volume-overrides` | One-time Longhorn volume policy corrections. | Applies narrow volume-level fixes without changing global Longhorn defaults. |

## Observability Coupling

App bundles can add:

- `ServiceMonitor` resources for metrics;
- `PrometheusRule` resources for alerts;
- Grafana dashboards through labeled ConfigMaps;
- OpenTelemetry exporter configuration pointing at the collector;
- log labels and trace IDs that connect Loki and Tempo.

The monitoring stack intentionally leaves selectors open so app projects can
contribute observability resources without editing the base monitoring install.

## DNS Coupling

Internal HTTP apps declare Traefik `Ingress` hosts. ExternalDNS watches those
Ingress objects and writes matching UniFi DNS records for the internal domain.
That keeps app hostnames Git-driven while the router remains the DNS authority.

## Backup and Compliance Coupling

Rancher Backup protects Rancher-managed state. Rancher Compliance provides CIS
scan definitions. These do not replace application database backups or storage
snapshots; they cover cluster management and compliance reporting concerns.

## Operating Notes

- Keep system chart repositories reconciled before HelmOp-based system apps.
- Treat monitoring, DNS, and secret operators as shared dependencies.
- Add app-level observability in the app project, not by editing the base
  monitoring chart for every app.
- Keep credential-bearing system bundles SOPS encrypted.
