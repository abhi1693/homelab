# Loki

This bundle installs the local log backend for the Rancher Monitoring namespace
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `loki`
- Release: `loki`
- Mode: single-binary Loki
- Storage: filesystem TSDB on a 20Gi Longhorn PVC
- Retention: 168 hours
- Gateway: enabled
- ServiceMonitor and chart rules: enabled

Read, write, and backend microservice replicas are disabled. This is a compact
home-lab deployment, not a horizontally scaled Loki topology.

## Producers and Consumers

`alloy-logs` and `alloy-faro` write logs through the Loki gateway. Grafana and
Prometheus are allowed to query or scrape Loki according to the network policy.

## Network Boundary

`loki-boundary` allows ingress from Alloy log pipelines, Grafana, Prometheus,
and Loki pods themselves. Egress is limited to DNS and Loki internal
communication ports.

## Operating Notes

- Increase the Longhorn PVC and memory limits before extending retention
  materially.
- Keep retention changes in `values.yaml`; do not tune the live StatefulSet by
  hand.
- Validate alongside `alloy-logs` when changing gateway or service naming.
