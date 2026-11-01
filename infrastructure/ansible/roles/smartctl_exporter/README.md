# Host SMART monitoring

Ubuntu Server 26.04 installs `smartmontools` and `prometheus-smartctl-exporter`
from the configured official Ubuntu repositories. The role renders the managed
systemd override, enables the service and validates device discovery and local
metrics. No additional archive or backports source is added.

Validation reads actual SMART/NVMe health and rejects missing health status,
critical warnings and failed smartctl results. It does not initiate self-tests.
Prometheus discovery and alerts stay in Git/Fleet; host exporter maintenance
uses this role's normal `main` and `validation` entrypoints.
