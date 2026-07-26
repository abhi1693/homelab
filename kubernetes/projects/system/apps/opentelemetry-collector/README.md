# OpenTelemetry Collector

Small OpenTelemetry Collector for application telemetry.

The collector receives OTLP metrics on `4317` and `4318`, batches them, and
exports them to the Rancher Monitoring Prometheus OTLP endpoint. It also
receives OTLP traces, applies tail sampling, and forwards retained traces to the
local Tempo service. Logs are intentionally not configured yet.

Tail sampling waits up to 10 seconds, retains every trace marked `ERROR`,
retains every trace slower than two seconds, and keeps 20% of remaining normal
traffic. The policies are combined as an OR, preserving failures and latency
outliers while reducing routine Tempo ingestion. The collector is a single
replica, so all spans for a trace reach the same sampling decision point.

Applications should send metrics to:

- `http://opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4318`
- `opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4317`

The collector exposes its own Prometheus metrics on port `8888` and health
checks on port `13133`.
