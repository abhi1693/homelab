# OpenTelemetry Collector

The monitoring migration routes both `prometheus-write-*` Services directly to
Prometheus's native HTTP port 9090. The processor NetworkPolicy permits 9090
and retains the legacy proxy port 8081 during the staged handoff and rollback
window. See the [monitoring migration runbook](../../../../../docs/runbooks/rancher-monitoring-migration.md)
for rollout ordering and exporter/queue verification.
The monitoring bundle also carries an additive `prometheus-native-write` policy
so port 9090 is admitted while this dependent bundle waits for monitoring readiness.

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

Delivery failure notifications include the collector pod, exporter, approximate
rolling ten-minute count, and first checks. With the pinned Collector's exporter
helper, `send_failed_*` records a failed outcome after the retry handler returns;
it is not an individual retry counter. Read collector errors to distinguish
non-retryable failures, exhausted retry windows, shutdown, and cancellation.
For metric exports, compare both Prometheus destinations before concluding that
both copies are lost. Counts at the gateway and processor stages must not be
added as distinct telemetry loss.

Queue saturation notifications report current utilization after five minutes
above 80%; queue pressure is a risk signal, not a permanent-loss count. The
Prometheus failure and queue rules share `incident: metric-delivery`, while the
Tempo export failure uses `incident: trace-delivery`. Mixed gateway metrics and
trace rules retain separate grouping because they do not establish which
downstream backend failed. Correlation labels support investigation; they do not
prove causality or suppress final delivery failures.

Applications continue to send telemetry to:

- `http://opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4318`
- `opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4317`

All desired state is Fleet-managed. Do not scale or restart either tier
manually; change the manifests here and let Fleet reconcile them.
