# Wardn Hub

Wardn Hub is deployed in the `wardn` namespace with separate backend and
frontend images from `ghcr.io/abhi1693/wardn-hub`. Webhook event deliveries are
processed by the `wardn-hub-events-worker` Deployment, which runs from the
backend image.

The frontend is exposed through the Cloudflare tunnel ingress at
`https://hub.wardnai.dev`. Browser API calls use the frontend's same-origin
Next.js rewrite to reach `wardn-hub-api` inside the cluster.

Authentication is configured for Clerk only through:

- `WARDN_HUB_AUTH_PROVIDERS=clerk`
- `WARDN_HUB_AUTH_DEFAULT_PROVIDER=clerk`
- `NEXT_PUBLIC_AUTH_PROVIDERS=clerk`

Runtime secrets, Clerk keys, and PostgreSQL credentials are managed through
`secrets.sops.yaml`.

Submission review automation runs as `wardn-hub-review-webhook`. Its Wardn Hub
API token and event signing secret are stored in
`review-webhook-secrets.sops.yaml`; the webhook pod syncs the
`submission.submitted` event rule on startup using those encrypted values.

Codex login is checked by the `wardn-hub-codex-login` Helm pre-install/pre-upgrade
Job. It mounts `wardn-hub-codex-config` at `/app/.codex` and runs device auth
only when the shared Codex state is missing. Backend automation pods mount the
same PVC and wait for that login state before starting Codex-backed review work.

## Observability

The backend API and events worker export OpenTelemetry traces over OTLP
HTTP/protobuf to the in-cluster `opentelemetry-collector` service in
`cattle-monitoring-system`. The app-level ConfigMap enables tracing and defines
the collector endpoint; each backend container sets its own service name and
Kubernetes resource attributes so traces appear separately in Grafana Tempo.
