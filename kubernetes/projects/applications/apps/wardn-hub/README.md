# Wardn Hub

Wardn Hub is deployed in the `wardn` namespace with separate
`ghcr.io/abhi1693/wardn-hub-backend` and
`ghcr.io/abhi1693/wardn-hub-frontend` images. Webhook event deliveries are
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

Submission review automation is DB-driven in Wardn Hub. Home-lab runs
`wardn-hub-review-worker` and `wardn-hub-fix-rejected-worker` as long-lived
worker Deployments. They do not expose webhook endpoints; each worker drains
eligible submissions from PostgreSQL, talks to Codex app-server, then sleeps and
checks again.

Codex review automation talks to `wardn-hub-codex-app-server` over its internal
WebSocket service. The app-server pod uses the public Node image, installs the
pinned `@openai/codex` version and checksum-verified `jq` release binary at
startup, and stores device-auth state on the 512Mi `wardn-hub-codex-home` PVC
through `CODEX_PERSISTENT_HOME=/codex-auth`.
`CODEX_HOME=/codex-home` is an in-memory runtime volume, and the startup wrapper
copies only `auth.json` from the PVC before launching Codex. `CODEX_MODEL`,
`CODEX_MODEL_REASONING_EFFORT`, `CODEX_WEB_SEARCH_MODE`, and
`CODEX_HISTORY_PERSISTENCE` are passed to Codex app-server as `model`,
`model_reasoning_effort`, `web_search`, and `history.persistence` config
overrides, so model selection, thinking level, first-party web search mode, and
local history retention are controlled at the app-server boundary. `RUST_LOG`
sets targeted app-server debug logging to stdout/stderr for `kubectl logs`;
plaintext Codex log files are not enabled. `CODEX_UNIFIED_EXEC=false` and
`CODEX_SHELL_SNAPSHOT=false` keep Codex on the non-unified shell runner because
the unified exec path has failed pre-shell process creation in this container
runtime.

When the PVC has no valid login, the app-server pod stays unready while the
Codex startup wrapper runs device authorization. The wrapper bounds
`codex login status` checks, runs one foreground Node device-auth flow, and only
continues into `codex app-server --listen ws://0.0.0.0:41237 --ws-auth
capability-token` after auth validates. Watch the pod logs for the device code,
complete the login, and the same container starts the WebSocket server. Review
and rejected-submission fixer pods use `WARDN_HUB_CODEX_APP_SERVER_URL` and the
shared `WARDN_HUB_CODEX_APP_SERVER_AUTH_TOKEN` secret to reach that service.
They do not mount Codex credentials themselves.

## Observability

The backend API and events worker export OpenTelemetry traces over OTLP
HTTP/protobuf to the in-cluster `opentelemetry-collector` service in
`cattle-monitoring-system`. The app-level ConfigMap enables tracing and defines
the collector endpoint; each backend container sets its own service name and
Kubernetes resource attributes so traces appear separately in Grafana Tempo.
