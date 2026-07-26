# Wardn Hub

Wardn Hub is deployed in the `wardn` namespace with separate
`ghcr.io/abhi1693/wardn-hub-backend` and
`ghcr.io/abhi1693/wardn-hub-frontend` images. Application background work is
processed by the `wardn-hub-worker` Deployment from the backend image.

All custom Wardn Hub Deployments retain two ReplicaSet revisions; Git and Fleet
history remain the primary rollback path as automated recommendations and image
releases generate new pod templates.

The frontend is exposed through the Cloudflare tunnel ingress at
`https://hub.wardnai.dev`. Browser API calls use the frontend's same-origin
Next.js rewrite to reach `wardn-hub-api` inside the cluster.

Authentication is configured for Zitadel through OpenID Connect:

- `WARDN_HUB_AUTH_PROVIDERS=oidc`
- `WARDN_HUB_AUTH_DEFAULT_PROVIDER=oidc`
- `WARDN_HUB_OIDC_ISSUER_URL=https://auth.abhimanyu-saharan.com`
- `WARDN_HUB_OIDC_REDIRECT_URI=https://hub.wardnai.dev/api/auth/oidc/callback`
- `NEXT_PUBLIC_AUTH_PROVIDERS=oidc`

Runtime secrets, Zitadel client credentials, and PostgreSQL credentials are
managed through `secrets.sops.yaml`. The `wardn-hub` Secret must provide both
`WARDN_HUB_OIDC_CLIENT_ID` and `WARDN_HUB_OIDC_CLIENT_SECRET` before this
configuration is reconciled.

The worker runs the application-owned `events`, `submission-review`,
`submission-repair`, `mcp-registry-sync`, `skill-maintenance`, and
`skill-import` job lanes.
Each lane holds a session-level PostgreSQL advisory lock for its lifetime.
Running more than one worker replica is safe: only one replica owns a given lane
at a time, and PostgreSQL releases the lock automatically if its worker exits or
loses the connection. Review and repair remain DB-driven, execute one
submission per child process, and use Codex app-server without exposing webhook
endpoints.

Skill security auditing is enabled through `WARDN_HUB_SKILL_AUDIT_ENABLED`.
GitHub imports and refreshes immediately drain the pending-audit queue after
their GitHub phase. The backend runs the pinned Cisco AI Skill Scanner locally,
stores one current result per snapshot, and exposes its 0-100 score, rank,
deductions, findings, and analyzer metadata. The `skill-maintenance` lane checks
for pending audits every minute and processes one snapshot per isolated child
process, so audit failures do not terminate the worker or require a one-off Pod.

The scanner LLM analyzer is separately enabled through
`WARDN_HUB_SKILL_AUDIT_LLM_ENABLED`. Wardn Hub exposes an ephemeral loopback
OpenAI-compatible endpoint to Cisco's unchanged LLM analyzer and backs it with
the same `wardn-hub-codex-app-server` service used by review automation. The API
Deployment and worker receive
`WARDN_HUB_CODEX_APP_SERVER_URL` from the shared ConfigMap and
`WARDN_HUB_CODEX_APP_SERVER_AUTH_TOKEN` from the shared Secret, so no scanner
provider API key is required. The scanner requires the LLM analyzer to complete
before an audit is stored. Cisco AI Defense, meta analysis, and VirusTotal
remain disabled.

Skill source refreshes run from the `skill-maintenance` lane at 04:43 every
Sunday in the `Asia/Kolkata` time zone. Each run executes
`python -m app.manage skills refresh`, reads active GitHub skill sources,
stores changed bundles in PostgreSQL, and audits changed snapshots through the
pending-audit queue in the same command.

New skill discovery runs from the `skill-import` lane at 03:17 every Saturday.
Its configured importer arguments search repositories named `skills` with at
least 1,000 stars, restrict results to GitHub-verified organizations, scan the
`skills` subfolder recursively, exclude owners already represented in Hub, and
stop after 500 matching repositories.
`WARDN_HUB_WORKER_SKILL_IMPORT_ARGUMENTS` can replace the complete filter set
without changing the worker image.

The daily MCP registry sync remains scheduled for 02:17 in the same time zone.
The next run and last result for all scheduled lanes are persisted in
PostgreSQL. A worker restart therefore cannot lose a due run; a command that was
interrupted before completion remains due and is retried by the next lane
owner. Job outcomes and durations are exported through the worker's Prometheus
metrics and structured logs instead of Kubernetes Job objects.
Registry source read timeouts are treated as unavailable metadata for that
source rather than aborting the full registry sync.

Codex review automation talks to `wardn-hub-codex-app-server` over its internal
WebSocket service. The app-server pod uses the dedicated
`ghcr.io/abhi1693/wardn-hub-codex-app-server` image, which preinstalls the
pinned `@openai/codex` version plus `bubblewrap`, `ca-certificates`, `curl`,
`git`, `ripgrep`, `jq`, and `python3`. Runtime auth and configuration are still
injected only through environment variables, the `wardn-hub` secret, and the
512Mi `wardn-hub-codex-home` PVC through `CODEX_HOME=/codex-auth`. Keeping the
live `auth.json` on the PVC persists automatic refresh-token rotation across
pod replacements. SQLite-backed runtime state uses
`CODEX_SQLITE_HOME=/var/lib/codex-sqlite` on a bounded `2Gi` `emptyDir`, so
high-volume local state cannot fill the authentication PVC. The startup wrapper
removes other prior Codex state before launch, while runtime scratch data stays
under `/tmp`. The image creates a writable
`CODEX_WORKDIR=/tmp/codex-work` and starts Codex from there. The Codex container
still runs privileged with an unconfined seccomp profile. This is
required on the current Raspberry Pi/K3s nodes because
unprivileged and setuid `bubblewrap` profiles cannot create the namespaces
Codex needs for read-only tool sandboxes.
`CODEX_MODEL`,
`CODEX_MODEL_REASONING_EFFORT`, `CODEX_WEB_SEARCH_MODE`, and
`CODEX_HISTORY_PERSISTENCE` are passed to Codex app-server as `model`,
`model_reasoning_effort`, `web_search`, and `history.persistence` config
overrides, so model selection, thinking level, first-party web search mode, and
local history retention are controlled at the app-server boundary. `RUST_LOG`
sets targeted app-server info logging to stdout/stderr for `kubectl logs`;
plaintext Codex log files are not enabled. `CODEX_UNIFIED_EXEC=false` and
`CODEX_SHELL_SNAPSHOT=false` keep Codex on the non-unified shell runner because
the unified exec path has failed pre-shell process creation in this container
runtime.

When the PVC has no valid login, the app-server pod stays unready while the
Codex startup wrapper runs device authorization. The wrapper bounds
`codex login status` checks, runs one foreground Node device-auth flow, and only
continues into `codex app-server --listen ws://0.0.0.0:41237 --ws-auth
capability-token` after auth validates. Watch the pod logs for the device code,
complete the login, and the same container starts the WebSocket server. Review,
rejected-submission repair, API, and skill-maintenance jobs use
`WARDN_HUB_CODEX_APP_SERVER_URL` and the shared
`WARDN_HUB_CODEX_APP_SERVER_AUTH_TOKEN` secret to reach that service. They do
not mount Codex credentials themselves.

The frontend builder, frontend Deployment, and cleanup CronJob share the
`wardn-hub-next-build-cache-nfs` RWX PVC. NFS CSI provisions its retained NAS
directory below `wardn/wardn-hub-next-build-cache-nfs`; Codex authentication
continues to use the separate Longhorn-backed `wardn-hub-codex-home` PVC.
The unused legacy `wardn-hub-codex-config` Longhorn claim has been retired; the
active Codex home claim is unaffected.

The consolidated worker requests `150m` CPU and `512Mi` memory with a `1536Mi`
memory limit. CPU remains burstable for review, audit, and delivery spikes.
The Codex app-server requests `90m` against an observed 7-day aggregate p99 of
about `73m`, and the frontend requests `30m` against about `22m` p99.

## Observability

The backend API and application worker export OpenTelemetry traces over OTLP
HTTP/protobuf to the in-cluster `opentelemetry-collector` service in
`cattle-monitoring-system`. The app-level ConfigMap enables tracing and defines
the collector endpoint; each backend container sets its own service name and
Kubernetes resource attributes so traces appear separately in Grafana Tempo.

The Codex app-server wrapper writes `[analytics] enabled = true` and `[otel]`
settings into the runtime `config.toml`. Codex log export is disabled with
`CODEX_OTEL_EXPORTER=none`, user prompt export remains redacted, and Codex
metrics are exported to the collector with `CODEX_OTEL_METRICS_EXPORTER=otlp-http`
over HTTP/protobuf. The metrics of primary interest are:

- `codex.api_request` and `codex.api_request.duration_ms`
- `codex.sse_event` and `codex.sse_event.duration_ms`
- `codex.websocket.request` and `codex.websocket.request.duration_ms`
- `codex.websocket.event` and `codex.websocket.event.duration_ms`
- `codex.tool.call` and `codex.tool.call.duration_ms`
- turn-level metrics such as `codex.turn.e2e_duration_ms`,
  `codex.turn.ttft.duration_ms`, `codex.turn.tool.call`, and
  `codex.turn.token_usage`

The collector forwards those OTLP metrics to Prometheus. Prometheus may expose
the metric names with its OTLP name normalization, for example by translating
dots to underscores. Unit-normalized duration names may also include an extra
unit segment such as `_milliseconds` before Prometheus histogram suffixes.

The shared OpenTelemetry collector converts delta-temporality metrics to
cumulative before forwarding them to Prometheus. Without that conversion,
Prometheus rejects Codex metric batches with invalid temporality/type errors.
