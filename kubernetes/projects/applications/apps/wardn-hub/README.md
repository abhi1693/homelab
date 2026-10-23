# Wardn Hub

Wardn Hub is deployed in the `wardn` namespace with separate
`ghcr.io/abhi1693/wardn-hub-backend` and
`ghcr.io/abhi1693/wardn-hub-frontend` images. Application background work is
normally processed by the `wardn-hub-worker` Deployment from the backend image.

AI processing is temporarily paused: the consolidated worker and Codex
app-server Deployments have zero replicas, and the find-skills refresh hook
completes without running an import. This pauses submission review and repair,
skill auditing and categorization, scheduled imports and refreshes, registry
sync, and event delivery. The API, frontend, and scoring service remain online.
Existing audit results, queued database work, Secrets, Services, and PVCs are
retained. Audit feature flags remain enabled to preserve access to stored results.

To resume through GitOps, restore both Deployments and their catalog entries to
one replica, restore their recommendation-profile scaling flags and replica
bounds to one, and restore the import command documented in
`find-skills-refresh-job.yaml`. Commit and push, then verify Fleet convergence,
worker health, and Codex readiness before expecting queued work to complete.

All custom Wardn Hub Deployments retain two ReplicaSet revisions; Git and Fleet
history remain the primary rollback path as automated recommendations and image
releases generate new pod templates.

The frontend is exposed through the Cloudflare tunnel ingress at
`https://hub.wardnai.dev`. Browser API calls use the frontend's same-origin
Next.js rewrite to reach `wardn-hub-api` inside the cluster.
Public registry pages keep their one-hour Next.js cache enabled. The frontend
also exposes the protected `/api/revalidate/registry` route for on-demand
registry cache invalidation; authenticate that route with the
`WARDN_HUB_REVALIDATE_TOKEN` value from the `wardn-hub` Secret.

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
When active, production uses one worker replica. During the temporary pause,
the manifest and recommendation profile hold the worker at zero replicas.
Running more than one worker replica remains safe if the manifest and profile
bounds are intentionally raised: only one replica owns a
given lane at a time, and PostgreSQL releases the lock automatically if its
worker exits or loses the connection. Review and repair remain DB-driven,
execute one submission per child process, and use Codex app-server without
exposing webhook endpoints.

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
When AI processing is active, every Wardn Hub Helm install or upgrade runs the
`wardn-hub-find-skills-refresh` hook after the API rollout is ready. That hook
uses the rollout backend image to re-import `skills/find-skills` from
`abhi1693/wardn-hub`, so the published bootstrap skill tracks the source that
ships with each new Hub image instead of waiting for the weekly catalog refresh.

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

The consolidated worker requests `370m` CPU and `1200Mi` memory with a `1536Mi`
memory limit. CPU remains burstable for review, audit, and delivery spikes.
The Codex app-server requests `180m` CPU and `1Gi` memory with a `4Gi` memory
limit. The higher cap preserves room above repeated near-`2Gi` review bursts
while still bounding runaway sessions; the recommendation profile can continue
tuning requests, but the memory limit stays in this manifest.

## Scoring upgrades

Upgrade the scoring service separately from the Hub backend and frontend. Its
source and release workflows require native ARM64 SBOM generation, strict
HIGH/CRITICAL and secret scans, and a real HTTP/scoring smoke against an isolated
read-only registry fixture. The smoke verifies Python 3.12.15, source/image/API
version parity, non-root identity, native extensions, signed scoring results and
unsigned webhook rejection, without writing to a registry.

Scoring 0.1.7 uses the private repository-owned
`ghcr.io/abhi1693/wardn-hub-scoring/runtime` package. Its normal Actions token
publishes the image; the earlier flat package remains available for rollback.
GitHub artifact attestations are unavailable for this user-owned private source
repository on the current account plan. Verify the exact successful release
reports and hash-checked embedded BuildKit provenance for image subject, source
revision and workflow run. This does not claim a separate signed GitHub artifact
attestation. Native scan, SBOM, smoke and immutable-promotion gates remain required.

Pin the published scoring image by immutable digest after those checks. Renovate tracks the published Docker tags and
retains digest pins. Preserve the existing Hub backend init-container pin during
a scoring-only upgrade. After Fleet converges, verify both health endpoints,
OpenAPI version, unsigned webhook rejection, zero restarts and the existing
paused worker/Codex state. Exercise signed production scoring only through
normal Hub events; keep synthetic signed requests in the isolated CI fixture.

## Observability

The backend API and application worker export OpenTelemetry traces over OTLP
HTTP/protobuf to the in-cluster `opentelemetry-collector` service in
`cattle-monitoring-system`. The app-level ConfigMap enables tracing and defines
the collector endpoint; each backend container sets its own service name and
Kubernetes resource attributes so traces appear separately in Grafana Tempo.

The Wardn Hub Product Metrics and Codex App Server dashboards are retired.
The dedicated Hub API/worker ServiceMonitor and its Prometheus ingress policy
are removed, and `CODEX_OTEL_METRICS_EXPORTER=none` disables Codex metric export
when the currently paused deployment is resumed. Existing time series age out
under normal Prometheus retention; no historical data is forcibly deleted.

Application traces and cluster-wide container logs/resource metrics remain
available through the shared observability stack. The Codex thread-saturation
alert remains because it uses shared cAdvisor metrics, not the retired scrape.
Codex log export remains disabled and user prompts remain redacted.

## Runtime image cohort and frontend cache

The backend, frontend and Codex app-server images form one application-version
cohort across all 14 image references, including init containers, release hooks
and paused deployments. Pin a verified immutable digest for each component in
the same GitOps change. Keep Scoring's independently released main image and
all paused replica settings intact. The Renovate policy guard rejects mixed
versions, missing digests and inconsistent component digests. Renovate follows
published Docker tags, groups the cohort, and requires review before merge;
grouping alone does not prove release completeness. Verify all three native
release reports and signed provenance before selecting their digests.

The frontend image uses `./docker-build-next.sh` for its full locked Next build
and Faro source-map preparation. Deploy that helper command with the new image.
Builder, restore and cleanup use identical `next-build-v8` keys: application
sources, build/Faro helpers, root and workspace dependency files, local packages,
public frontend variables, the internal API base URL, application version and
Node version. Private credentials are excluded from the key inputs.

Validate these contracts with
`python3 -m unittest discover -s kubernetes/projects/applications/apps/wardn-hub/tests -v`
and `python3 scripts/check-renovate-policy.py`.
