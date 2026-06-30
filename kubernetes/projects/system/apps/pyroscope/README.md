# Pyroscope

Lightweight single-pod Grafana Pyroscope backend for continuous profiling.

This first deployment is intentionally scoped for a k3s home lab:

- one ARM64 pod in `cattle-monitoring-system`;
- local filesystem storage on a `2Gi` `emptyDir`;
- 24-hour block retention and query lookback;
- Grafana access through the provisioned `Pyroscope` datasource;
- Prometheus scraping of Pyroscope's own `/metrics`;
- no application profiling traffic until an app is explicitly instrumented.

The pod uses the Pyroscope v2 storage architecture in single-binary mode. The
storage is non-durable by design so this can be evaluated without adding
Longhorn write load. Move this to a PVC only after profile volume and resource
usage are known.
