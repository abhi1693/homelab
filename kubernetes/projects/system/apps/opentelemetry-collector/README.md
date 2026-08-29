# OpenTelemetry Collector

Highly available, local-only OpenTelemetry ingestion and processing for
application metrics and traces. Logs are intentionally not configured yet.

The deployment uses two separate failure-isolated tiers:

1. Two stateless `opentelemetry-collector` gateway replicas receive OTLP gRPC
   and HTTP traffic through the stable application-facing Service.
2. Each gateway uses the OpenTelemetry load-balancing exporter to route all
   spans for one trace ID and all points for one metric stream ID to the same
   downstream `opentelemetry-processor` replica.
3. Two processor StatefulSet replicas apply stateful delta-to-cumulative metric
   conversion and tail sampling. Each metric batch is exported to both
   Prometheus replicas, while sampled traces are exported to the local Tempo
   service.

Trace-ID affinity is required because tail sampling must see every span in a
trace. Stream-ID affinity provides the same correctness boundary for
delta-to-cumulative metric state. The gateways discover the two stable
StatefulSet hostnames through the Kubernetes EndpointSlice resolver. Their
ServiceAccount can only read EndpointSlices in
`cattle-monitoring-system`, and their Cilium policy permits only Kubernetes API
access required by that resolver.

Both tiers use hard hostname anti-affinity and a `minAvailable: 1`
PodDisruptionBudget. A gateway or processor loss therefore leaves an accepting
OTLP endpoint and a stateful processing path available. A processor failure can
still lose its in-memory, not-yet-decided traces and reset delta conversion for
streams reassigned to the surviving processor; there is no external state or
cloud dependency that can preserve those in-flight buffers.

Tail sampling waits up to 10 seconds, retains every trace marked `ERROR`,
retains every trace slower than two seconds, and keeps 20% of remaining normal
traffic. Sampled and non-sampled decision caches retain late-span decisions.

Each processing replica exports every metric batch to both ordinal-specific
Prometheus OTLP Services. The exporters use one queue consumer, bounded
32-batch queues, and two-minute retry windows. Serial delivery preserves batch
order after a replica outage and prevents storage recovery from producing a
concurrent retry burst. Tempo delivery has a five-minute retry window and a
bounded queue.

Prometheus alerts cover reduced replica counts, fewer than two resolved
processing backends, gateway and downstream delivery failures, and saturated
queues. Both tiers expose collector metrics on port `8888`.

Applications continue to send telemetry to:

- `http://opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4318`
- `opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4317`

All desired state is Fleet-managed. Do not scale or restart either tier
manually; change the manifests here and let Fleet reconcile them.
