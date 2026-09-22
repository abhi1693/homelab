# DevFeed

Fleet-managed developer news platform, pinned to release **0.0.30** and its verified
ARM64 image digests. Approval and publication require an explicit article page-kind
classification; missing or uncertain classifications stay blocked.

Renovate tracks stable `X.Y.Z` Docker tags for all six DevFeed images on GHCR,
grouping runtime, init-container, and migration-hook updates while refreshing
their SHA-256 pins. Commit tags, moving tags, and prereleases are excluded;
Kubernetes continues pulling the pinned images through Harbor.

Reader language preferences support one or more languages, defaulting to English.
My feed and Latest retain source/content filters and offer Most liked sorting.
Source/topic discovery is paginated and restricted to the selected article languages.
Web, Chrome and Edge share the reader; extension 0.1.9 store publication is separate.
Sources added by import, the admin form, or CLI share discovery and review. Imports
remain pending until reviewed; full-auto mode uses AI review and approval enables polling.
The pre-upgrade hook verifies schema `0017` before replacing application workloads.
Release 0.0.30 applies migration `0017` for identity-free moderated search-query
statistics before replacing application workloads.

| Entry point | Routing | OIDC client |
| --- | --- | --- |
| `https://devfeed.tech` | Public Cloudflare Tunnel, reader frontend only | `390346916430350165` |
| `https://admin.devfeed.home` | Internal Traefik, home-local-ca certificate | `390346721797867349` |

Search and topic Follow actions return to the originating page after sign-in;
search queries and filters survive the callback. Return URLs remain restricted
to known local paths and search parameters.

The reader session uses a 30-day inactivity timeout and a 90-day absolute lifetime.
Returning to a visible tab renews the local session independently of the provider's
short-lived ID token. The session-policy change requires one fresh login when the
new application release is deployed; existing session records are not migrated.
Admin session policy is unchanged.

Both clients use `https://auth.abhimanyu-saharan.com`, organization
`389593181982820082`, PKCE and secure cookies. Administration additionally requires
`superuser`. Register the callbacks `/api/v1/user/auth/callback` on the public origin
and `/api/v1/admin/auth/callback` on the admin origin in Zitadel. Internal clients
must trust the home CA and resolve `admin.devfeed.home` to `192.168.3.3`.
The admin ingress permanently redirects HTTP requests to HTTPS, preserving the
path and query string. Its redirect middleware is scoped to this application.

## Services and automation

- Two replicas each of the reader frontend, admin frontend, public API, user API
  and admin API. Each pair has required hostname anti-affinity and a disruption
  budget retaining at least one available replica.
- **One dedicated worker each** for ingestion and source enrichment, **three article-enrichment workers**,
  plus **two image workers**. The obsolete background deployment and its disruption
  budget have been removed; each category has its own consumers.
- **Five dedicated article-analysis workers** and **one each** for topic analysis, source analysis,
  research verification and relationships, plus **one pooled AI worker** for legacy
  deliveries and additional fair queue coverage. Ten AI consumers retain shared
  provider cooldowns; topic workers are reduced from three to one.
- One scheduler publishes each physical queue with its own dispatch budget.
  Its health thread renews the 120-second heartbeat every 20 seconds during long
  cycles, but stops renewal after five minutes without a successful cycle. It also
  refreshes quota independently of dispatch work. The scheduler requests 500m CPU;
  its liveness probe allows 15 seconds for Python startup and Redis discovery.
- **Two dedicated notification workers** prevent delivery starvation while
  extraction workers process article pages.
- The 13 busiest worker pods (article analysis/enrichment, ingestion, images and
  notifications) share a preferred hostname spread with `maxSkew: 1` across eligible
  worker nodes, plus preferred anti-affinity to the PostgreSQL primary. CPU
  reservations take precedence over equal pod counts. `nodeTaintsPolicy: Honor`
  excludes the tainted control plane.
  A single shared constraint avoids Helm merging duplicate hostname entries.
  CPU requests are 300m for article analysis,
  500m for article enrichment, 400m for ingestion and notifications, and 350m
  for images, replacing uniform 100m requests. Replica counts and CPU burst
  capacity are unchanged.
- **One solver worker** consumes browser-challenged enrichment jobs, using the
  existing remote browser service in `media` without installing browsers in workers.
- **One Typesense 30.2 instance and one dedicated search indexer** serve federated
  article/topic/source/tag search. Typesense is internal-only with a retained 10Gi
  Longhorn volume; the API receives only its restricted query key. Typesense requests
  100m CPU and Chimely requests 75m, with no CPU limits. The
  [September 19 resource review](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-09-19-cpu-sizing-review)
  records the usage evidence; busy worker reservations remain unchanged.
- One dedicated Codex service and one Chimely service; shared Valkey Sentinel.

`DEVFEED_FULL_AUTOMATION=true` enables bounded scheduling.
Full automation activates the app's evidence-gated topic/source
approval, research and reanalysis workflows. New sources have polling enabled;
only approved sources are ingested. AI workers and the admin API connect to
`wss://devfeed-codex.devfeed.svc.cluster.local:4501` with a separate bearer token and
verified private CA. AI readiness and shared provider cooldown checks apply to every
AI queue; background workers continue processing while AI queues are paused.
Release `v0.0.16` uses a 30-second shared pause for transient upstream
`serverOverloaded` responses, including RPC setup failures and corrective retries.
Rate and usage limits retain the five-minute minimum and longer provider reset
windows. Deferred jobs retain their retry allowance. Fresh article analysis and
extraction each receive a dedicated queue lane and half the dispatch budget;
older work retains its own capacity and has no eligibility cutoff.
Adjust each dedicated deployment through Git to change its capacity.
Worker probes verify the live Redis registration with a 15-second timeout and
three consecutive failures before restart. This allows Python startup and Sentinel
discovery to tolerate brief node delays without restarting healthy consumers.
Codex has no ingress and the model credentials remain solely
on its retained 10Gi Longhorn home. SQLite runtime state is separated with
`CODEX_SQLITE_HOME=/var/lib/codex-runtime` on a 512Mi disk-backed `emptyDir`.
Analysis threads are already ephemeral; the deployment also disables local conversation-history
persistence and uses targeted info/warn console logging.

The `log-retention` sidecar checks SQLite diagnostic logs every 30 seconds. It
removes DEBUG/TRACE records and records older than 24 hours, retains at most the
newest 2,000 records within a 16MiB body/metadata budget, checkpoints WAL files,
and vacuums when at least 8MiB of pages can be reclaimed. The volume limit is a
last-resort guard, not the retention mechanism. A stale 90-second heartbeat fails
readiness and liveness. Only log database files are opened; the sidecar does not
mount the authentication PVC. Validate retention after Codex upgrades because
its SQLite log schema is an internal interface.

The Recreate strategy stops the previous server before `remove-legacy-logs`
unlinks exactly `logs_2.sqlite`, `logs_2.sqlite-wal`, and `logs_2.sqlite-shm` from
the old home. Authentication, configuration, model cache and other state files
are preserved. Runtime SQLite state is disposable across pod replacements;
DevFeed's durable jobs and results remain in PostgreSQL.

Validate changes with:

```sh
node --test kubernetes/projects/applications/apps/devfeed/codex-log-retention.test.cjs
kubectl kustomize kubernetes/projects/applications/apps/devfeed
```

On an empty Codex volume, the `chatgpt-login` init container runs device sign-in.
Read its logs and complete the displayed browser authorization. This is a separate
ChatGPT sign-in, never a copy of local or Wardn Hub credentials. Restarts reuse
existing sign-in state. If sign-in is incomplete, the pod waits before starting
Codex; analysis workers wait for account readiness.

## Feed response limits

Production accepts RSS/Atom responses up to 20,000,000 bytes (20 MB), including
expanded gzip content, through `DEVFEED_FEED_MAX_BYTES` in the shared ConfigMap.
This applies to admin previews, source submissions, source review and ingestion;
HTML/discovery response limits and the 500-entry parsing limit stay unchanged.
Pod-template annotations roll the feed-consuming APIs and workers when this value
changes. Keep those annotations aligned with the ConfigMap. To roll back, restore
the prior limit and annotations in Git and let Fleet reconcile.

## Data and secrets

The shared CloudNativePG bundle owns retained `devfeed` and `devfeed_chimely`
databases and roles. Two `devfeed-rw` session poolers provide up to 20 backend
connections per database; each role allows 24. Release 0.0.30 uses SQLAlchemy NullPool
for all Python services: `DEVFEED_DATABASE_POOL_ENABLED=false` returns connections to
PgBouncer at session close, without a second retained application pool. HTTP admission
is bounded independently at 16 concurrent requests and 32 streams per API process;
overload is rejected before opening a database connection. There is no application
connection-acquisition queue. Workers release sessions before external work.
TCP keepalives and an 8-second TCP user timeout bound connection failure detection.

Before each Helm upgrade, `devfeed-migrate` runs the release image against the
direct writer service and applies pending schema migrations. Helm blocks the
upgrade if migration fails. The `before-hook-creation,hook-succeeded` policy
removes an older hook Job before the next attempt and deletes successful hook
Jobs automatically; failed hooks remain available for diagnosis. The hook uses
existing application configuration, secrets and service account, so it runs on
upgrades, not initial installation.

The v0.0.17 pre-upgrade hook retains schema `0009`, introduced in v0.0.10 for
persistent per-topic decision budgets. It performs no content rewrite. Backends
require `0009`; v0.0.10 is schema-compatible, while an image-only rollback to
v0.0.9 fails its schema check. Prefer v0.0.11 for its corrected discovery guard
and evidence selectors.

Tiered routing uses Luna low for drafting/article/source work and Luna medium for
research/verification, with one bounded Terra correction for invalid topic output.
A usable source URL skips model discovery; otherwise a single search returns
candidate URLs for backend fetching. Drafting and verification reuse the saved
evidence, with schema-constrained excerpt IDs. A topic gets at most five calls,
four searches, 64,000 accounted tokens (at most 40,000 per call) and 240 seconds, with checkpointed source evidence and no automatic budget refill.
Limits stop further admissions; streamed usage can arrive after tokens are spent.
Uncertain outcomes stay pending/deferred rather than being rejected. Relationship
research and verification use the same quota-paced admission as article, source and
topic inference. The scheduler samples the account weekly quota once per minute,
using the same authenticated TLS endpoint, CA bundle and network-policy client
label as the AI workers. This also gives the scheduler and workers a shared quota key.
The remaining allowance, less a 20% reserve, is spread over the time until reset,
with a fixed allowance for each UTC day (prorated for a partial first day). Other
clients using the same account reduce the remaining headroom. Missing/stale quota
data pauses AI admission; background fetching continues. There is no fixed daily
relationship call cap in this mode and topics do not block relationship work.
Dedicated workers and provider cooldowns remain in place. The Overview charts separate actual decisions, usage, failures and
unresolved work. Production admits up to two decisions per observed available topic worker,
with a ceiling of eight and a pause during provider cooldown. One healthy dedicated
topic worker yields a two-job window; the pooled AI worker contributes only when
available. Dedicated queues isolate work without bypassing model capacity checks.
Topic evidence fetches run concurrently and public evidence can be reused for at most
five minutes without renewing its validation timestamp. Valid drafts survive malformed
verification retries; independent verification and whole-workflow budgets still apply.

Content-based AI processing has no publication date cutoff. The shared production
ConfigMap explicitly sets `DEVFEED_AI_CONTENT_NOT_BEFORE` to an empty string; old
and undated articles can be submitted subject to normal source approval, evidence,
and capacity checks. Matching pod-template annotations roll all consumers.
AI article summaries and descriptions are generated and validated in English,
while the source language and original-language classification evidence are retained.
Admin reporting uses separate bounded database connections and cached background
Overview snapshots. Source review notifications and orphaned queue deliveries recover
through the normal scheduler.

A completed post-upgrade recovery granted the 14 identified v0.0.10 canaries
one audited allowance while preserving prior spending. Its temporary hook has
been removed; the schema migration hook remains the only ongoing upgrade Job.

DevFeed uses shared Valkey Sentinel set `valkey`, database **10**, through
`valkey.valkey.svc.cluster.local:26379`. The data URL supplies DB 10, while Sentinel
discovers the primary. Access is restricted by network policy. The former Redis
Deployment, Service, Secret, network policy and 2Gi Longhorn PVC have been removed
after verified cutover. The completed copy Job and its script ConfigMap are removed too. The completed inbox provisioner created separate Chimely
user/admin environments and stored each consumer's credentials on its own retained
1Gi NFS volume. Only the dedicated notification workers receive delivery keys. Admin/user APIs
receive only their audience's signing secret. The completed provisioner used the same non-root UID as the consumers and a
shared volume group.

SOPS Secrets Operator owns database, service-token, Chimely bootstrap and
registry secrets. No plaintext credentials belong in this repository.

Network policies default-deny traffic and allow only the service pairs, DNS,
database access, required public HTTP(S) fetches, internal admin ingress and the
public reader tunnel. The matching Cloudflare connector egress rule is maintained
in its own bundle. There is no public route to either account API, administration,
Redis, Chimely or Codex; browser account requests pass through their own frontend.

## Validation and rollout

```sh
kubectl --kubeconfig ~/.kube/config kustomize kubernetes/projects/applications/apps/devfeed
python scripts/sync-readme-versions.py --check
kubectl --kubeconfig ~/.kube/config get pods,deploy,job,pvc,ingress -n devfeed
kubectl --kubeconfig ~/.kube/config logs -n devfeed deploy/devfeed-codex -c chatgpt-login
```

Release images must pass DevFeed's ARM64 tests, scans and smoke checks before
Fleet is pointed at them. Compare the ARM64 digests through GHCR and Harbor, then
verify Fleet's desired/applied deployment IDs, ready replicas, authenticated Codex
readiness, and both user-visible origins. Commit all desired-state changes; do not
repair this deployment using imperative Kubernetes mutations.

Release `v0.0.9` uses immutable digest pins for all six application runtime images.
[Release CI](https://github.com/abhi1693/devfeed.tech/actions/runs/34768134222) passed
3,475 application tests, CodeQL, security scans and six ARM64 runtime smoke checks.
The release image manifest records the exact attested digests. Verify attestations
with `--signer-workflow abhi1693/actions/.github/workflows/container-images.yml`,
`--source-ref refs/tags/v0.0.9` and the release commit as `--source-digest`. Verify GHCR and
Harbor parity before publishing GitOps pins; keep each main/init container aligned.

The migrations preserve existing accounts, content and preferences. They add schema
that `v0.0.8` readiness does not accept: a code-only rollback to that version is not
sufficient. Prefer a compatible forward fix. Any database restore or downgrade
requires a separately reviewed recovery operation; retain all PVCs and credential volumes.

## Search and solver operation

`devfeed-search-indexer` runs collection/key setup and consumes the PostgreSQL outbox
in batches of 200. Migration `0003` queues existing records for the initial backfill.
The indexer publishes a local heartbeat after successful batches; readiness detects
stalls. Public search uses only `documents:search` credentials, while the indexer and
Typesense alone receive the management key. Both keys are independently generated
and encrypted in `search-secrets.sops.yaml`. No search port is exposed externally.
The index is rebuildable from PostgreSQL; preserve credentials when replacing it.

The Raspberry Pi 5 nodes use 16KiB kernel pages. Typesense must use the official
`30.2-arm64-lg-page16` image, pinned by digest; the ordinary ARM64 build aborts with
`jemalloc: Unsupported system page size` on these nodes. Preserve the
`-arm64-lg-page16` variant when updating Typesense.

The solver worker consumes only `solver`; ordinary workers automatically hand off
recognized browser challenges. Only that worker receives `DEVFEED_SOLVER_SERVICES`.
Its network policy permits the existing `flaresolverr.media` endpoint, public publisher
HTTP(S), and the shared database/Valkey/Codex dependencies. It does not receive
notification delivery credentials or persistent ChatGPT state. Provider success is
not guaranteed: old terminal failures need an explicit retry, and unsupported
challenges remain errors rather than being accepted as article content.

The production reader explicitly enables analytics and exposes `/legal/terms`,
`/legal/privacy`, cached sitemaps, AI discovery documents and social-preview metadata.
Local Compose retains its separate analytics-disabled default.

## Availability and Valkey migration

The [staged cutover runbook](valkey-migration.md) records the coordinated copy of
Redis state into shared Valkey Sentinel database 10. Runtime clients now use
Sentinel; the one-time migration resources have been pruned. Shared Valkey has one primary and two
replicas across three nodes, with expanded memory headroom for DevFeed.

Two frontend/API replicas tolerate one pod or node failure when their shared
dependencies remain available. PostgreSQL has three instances and the dedicated
pooler has two replicas. Typesense, the search indexer, solver worker, dedicated Codex service, scheduler, Chimely and NFS
credential storage remain single-instance dependencies. This is web/API
redundancy, not end-to-end HA; async Valkey replication can lose unreplicated
writes during failover.

The queue upgrade preserved Redis delivery identities. The legacy `analysis`
queue and its in-flight work drained before the temporary AI pool was removed.
Rollback requires retaining consumers for the new queues until they drain, and a
schema-compatible application; prefer a forward fix over a schema downgrade.

## Observability

DevFeed has private port-9100 metrics on every application API, frontend, worker,
scheduler, indexer and the cached product exporter. A PodMonitor admits only
Prometheus; no application Service/Ingress exposes metrics. Alloy Faro additionally
reaches frontend port 9100 for private source maps. Faro ingestion is an intentional
same-origin public POST endpoint that filters telemetry and forwards with a
server-only encrypted key. Frontends alone consume `devfeed-faro`.

The existing Alloy/Loki, OTel/Tempo and Pyroscope stacks collect sanitized logs,
traces and CPU/heap profiles. Grafana's **DevFeed** folder contains availability,
queue/worker/product and diagnostics dashboards. Two private blackbox exporter
pods probe the public reader at `https://devfeed.tech/latest` and internal
service readiness/login every 30 seconds. They also probe the public
Cloudflare endpoints for the blog, portfolio, ShipyardHQ, imgproxy,
Launchboard, Wardn AI, and Wardn Hub; the monitoring bundle alerts on endpoint
failure, slowness, or missing probe data.
The reader probe requires HTTP 200 without redirects; `/` redirects to `/latest`.
Article enrichment has three consumers to drain eligible article-page extraction work;
this pool does not increase AI-provider concurrency. Revert the replica change through Git
if database or fetch capacity regresses.
PrometheusRules include multiwindow 99.9% availability burn, missing telemetry,
workload/restart/memory, queue delay/capacity/leases, failures/retries and search lag.

Run `python scripts/check-devfeed-observability.py` from the repository root to
validate dashboard PromQL and alert scenarios, then the standard manifest checks
and server dry run. Follow the application's
[metric definitions and runbooks](https://github.com/abhi1693/devfeed.tech/blob/v0.0.9/docs/observability.md).
Deployment must verify actual scrape targets, HTTP probes, logs, traces, profiles,
browser ingestion and public port/source-map isolation. SDK initialization alone
is not proof of delivery. Pyroscope retains its existing 24-hour ephemeral storage;
this change does not replace that backend or discard existing profile history.

Migration hooks are owned by Helm and are intentionally absent after successful
execution. Verify the hook result in Helm release history, database revision and
index validity; the absence of a completed hook Job is expected. See
[migration lifecycle](migrations.md) for operations and initial provisioning.

Worker deployments use `devfeed-worker-<type>`, including dedicated pipeline workers and `ai`
for shared pools. Replica counts and queue subscriptions are unchanged by naming.

The workload catalog mirrors the dedicated worker replica counts, including the
five dedicated background pipeline consumers, so capacity recommendations use the same intent.

The admin Overview serves 33 independent chart requests with per-panel shimmers
and retries, shared short-lived snapshots, and bounded reporting concurrency.
The workload chart includes all logical job types. Article extraction follows
validated immediate HTML redirects and ingestion excludes navigation metadata.

With full automation, v0.0.17 rejects pending, unpublished articles when the
publisher returns HTTP 404 or 410 and no publisher summary or extracted text is
available. Editorial reviews record the extraction job, HTTP status, and policy.
Existing decisions and usable publisher text are preserved; transient failures,
blocked requests, and empty successful responses do not trigger rejection.

## Browser extensions

The web gateway and user API allow these exact DevFeed extension IDs:

- Chrome Web Store: `iihaipjedchahiehignbngclgpklbddo`.
- Microsoft Edge: `hliakjocndflpkmfajndigbpngfcekdm` (owner-supplied; also the
  stable unpacked development ID).

Session and CSRF validation remain required. Keep `DEVFEED_USER_EXTENSION_IDS`
in both deployments synchronized if store IDs change; never use a wildcard
origin. Website GA4 uses `G-N4V5CW5C0M` and starts after interaction. Extension
Measurement Protocol uses the separate `G-Y1MNJGMGCD` stream. The web deployment
requires `devfeed-extension-analytics/DEVFEED_EXTENSION_GA_API_SECRET`, provisioned
as a SOPS-encrypted secret before reconciliation. Edit
`analytics-secrets.sops.yaml` with `sops` and set
`spec.secretTemplates[0].stringData.DEVFEED_EXTENSION_GA_API_SECRET`; the initial
empty value keeps the relay disabled. Never place that secret in a
ConfigMap, extension bundle, or plaintext Git file. The public relay configuration
at `/api/v1/extension/analytics` reports enabled only when all required values are
present. Roll back by disabling `DEVFEED_EXTENSION_ANALYTICS_ENABLED` through GitOps.
Store submission is independent of the application rollout.

## Managed article images

Two dedicated Images worker replicas process jobs concurrently and download originals through the application's SSRF-safe
fetcher, stores them in one production R2 bucket, asks the internal
`http://devfeed-imgproxy:8080` service for responsive WebP thumbnails, and uploads
those thumbnails to the same bucket. Readers load the resulting objects from
`https://images.devfeed.tech`; imgproxy has no ingress and no S3 credentials.
The bucket custom domain must serve `originals/` and `thumbnails/` over HTTPS.
Only the Images worker receives bucket-scoped read/write credentials from
`image-storage-secrets.sops.yaml`. Edit that file with SOPS; the endpoint is the
account origin without a bucket suffix. The worker and proxy share signing values
from `imgproxy-secrets.sops.yaml`, independently generated for DevFeed.

Imgproxy v4.0.15 runs one ARM64 replica with two processing workers, a bounded queue,
100m CPU/256Mi memory requested, and 1 CPU/512Mi memory limits. Its source allowlist
contains only the production bucket's `originals/` prefix. Network policies allow
only the Images worker to reach its HTTP port; proxy downloads use public HTTPS.
Originals and thumbnails persist in R2; no new PVC or public proxy route is needed.

Existing articles continue using their publisher image until the Images pipeline
finishes storage. The normal Images worker owns steady-state processing and durable
retries; source and topic logos are not part of this article-image pipeline.

Release 0.0.23 fixes source approval with minority uncertain entries and topic research
for computing concepts and disciplines. Schema remains 0013; existing deferred
reviews require targeted reprocessing.

Worker capacity favors article analysis while its older eligible jobs drain. Keep
two image consumers for steady-state processing and parallel recovery after
backfills. Reassess the five article-analysis replicas after the backlog clears;
use arrival rate, oldest eligible-job age, worker busy time and provider allowance,
rather than CPU alone. Leave the shared provider pacing and reserve enabled.
Revert replica changes in Git if queue latency or provider pressure regresses,
and verify Fleet convergence before judging the result.

Deployment alerts exclude deliberately scaled-to-zero workloads. The public reader
probe follows the homepage redirect to `/latest`.

## Release 0.0.24

Preserves generic campaign attribution through guest redirects, corrects Edge extension
analytics, and removes the unused admin graph explorer. Includes publisher diversity
for Latest, immediate search filters, source deduplication and verified unrelated-source
rejection, plus database concurrency and bounded analysis history improvements.

The migration hook adds nullable history-retention markers and builds discovery/retention
indexes concurrently. It does not immediately prune history or repair publication data.
Check for invalid indexes before retrying an interrupted migration. Schema 0014 is
required by the new services; old services require 0013 and can lose readiness during
the transition. Preserve the migrated schema and roll forward with compatible images
if recovery is needed.

Chrome and Edge 0.1.4 ZIPs accompany the application release. Browser-store submission
and approval are separate from this Fleet rollout.

The 0.0.24 rollout expands the retained Codex home from 5Gi to 10Gi after startup
encountered a full filesystem. Longhorn supports online expansion; authentication
and session data are preserved. Monitor usage before the added capacity fills.

## Release 0.0.25

Extends reader sessions to 30 days of inactivity with a 90-day absolute limit across
web, Chrome and Edge. Existing sessions require one fresh login. Includes scheduler
heartbeat/stall handling, lower sitemap and publication-query cost, stricter source
evidence checks, explicit temporary solver retries, and RSS/Atom URL fixes.

No new migration is required; schema 0014 remains current. The migration hook checks
the existing schema before services roll. All six application images are pinned to
the verified release digests. If rollback is needed, revert these image pins through
Fleet to 0.0.24; no schema rollback or data cleanup is needed. Completed maintenance
Jobs retain their original image pins.

Chrome and Edge 0.1.5 packages accompany the release and pass the reader browser
parity gate. Store submission and approval remain separate from this rollout.


## Release 0.0.26

Source policy v5 admits high-confidence, evidence-backed sources without requiring
80% of recent articles to qualify. It covers software product management, growth,
AI product building, engineering leadership, and related careers. Individual article
review stays independent; source rejection retains the stronger 80% evidence threshold.
Eligible pending assessments from older policy versions are requeued automatically;
active and exhausted jobs remain protected from duplicate or unbounded retries.

The admin source page has a Relevance tab immediately after Details. The summary and
article evidence appear side by side, with five-entry pages and classification filters.
Older assessments explain that their recorded result used an earlier policy.

No new migration is required; schema 0014 remains current. All six runtime images and
schema-check init containers use the release's verified digests. Roll back by reverting
these pins through Fleet to 0.0.25. Recorded source decisions are retained and require
explicit editorial review to reverse. Completed maintenance Jobs retain their original
image pins. Chrome and Edge 0.1.6 packages are built and covered by the reader parity
gate; browser-store submission and approval are separate from this deployment.


## Release 0.0.27

Article feeds and search use the shared reader infinite-scroll boundary without
More articles controls. Loading, retry, and end states remain available on the
website and in Chrome and Edge 0.1.7. Both extension ZIPs are release artifacts;
browser-store submission and approval remain separate.

The previously merged database work reduces taxonomy and feed-facet query load,
bounds cached catalog snapshots, and keeps personal feeds on a six-hour refresh
schedule. The pre-upgrade hook advances schema 0014 through migrations 0015 and
0016, adding transactional catalog revisions and two concurrently built indexes.
Source relevance policy and pending-source decisions are unchanged.

All runtime and schema-check images use the verified release digests. Completed
maintenance Jobs retain their original pins. Verify schema 0016, Fleet's
desired/applied revision, ready replicas, and public pagination after rollout.
Do not perform an image-only rollback to 0.0.26: its readiness contract expects
schema 0014. Prefer a schema-compatible roll-forward; a full rollback requires
tested coordinated migration handling.

### Article-derived proposal pause

`DEVFEED_ARTICLE_TOPIC_PROPOSALS_ENABLED=false` pauses new article-tag topic
proposals and research/approval of pending article-derived drafts, including already
queued jobs. It is independent of full automation. Imported proposals, article
ingestion, and classification against existing topics continue. Existing drafts,
approved topics and job history are retained. Restore `true` and roll the affected
services through Fleet to resume. This pause does not yet enforce a minimum number
of supporting articles per topic.

### 0.0.28 worker health rollout

Workers expose a local parent-heartbeat file at `/tmp/devfeed-worker-health.json`.
Readiness and liveness use `python -m devfeed_core.worker_health`, avoiding a Redis
connection and settings import for every probe. The runtime image and probes must
roll together. Existing CPU-worker placement rules and the current 300m article
analysis CPU request are preserved; other busy AI roles request 250m.

## Production health remediation

Release 0.0.29 removes the legacy application pool size/overflow settings. Frontend
telemetry embeds the package release version at build time; the legacy version
fallback has been removed from the shared telemetry ConfigMap.
After a release, verify user/admin HTTP metrics, reader article retry, scheduler
cycle time, and the shared Alloy/Loki delivery alerts, not just pod readiness.

The web/admin pod templates carry the telemetry ConfigMap SHA-256 annotation to
apply environment-based compatibility-label corrections to running processes.
Update that annotation when changing the shared telemetry ConfigMap for those
frontends; editing a ConfigMap alone does not refresh process environment.

Codex keeps app-server lifecycle INFO logs but limits core, model-manager and
provider-transport modules to WARN. Their per-event INFO traces dominated replay
bursts and shared Loki rate-limit rejections during the health rollout. Warnings,
errors and DevFeed durable job logs remain available; temporarily increase only a
specific module through GitOps when debugging. Changing the filter replaces the
single Codex pod; in-flight sessions can reconnect/retry through durable jobs.

### 0.0.29 release verification and rollback

The six image references and migration hook come from the successful `v0.0.29` CI
image manifest. Verify registry mirror digest parity, Fleet desired/applied equality,
ready workloads without new restarts, schema 0016, and live feed/settings behavior.
If rollback is needed, revert this release commit through Git so images and pool
configuration return together. Preserve database contents, PVCs and schema 0016;
completed maintenance Jobs are intentionally left at their original image pins.

### 0.0.30 release verification and rollback

The six application image references and migration hook come from the successful
`v0.0.30` CI image manifest. Verify registry mirror digest parity, Fleet
desired/applied equality, ready replicas without new restarts, schema `0017`,
search-indexer reconciliation, and live search/onboarding behavior. The existing
Typesense `30.2-arm64-lg-page16` deployment remains compatible with the release;
no Typesense image or PVC change is required. The restricted reader query key is
scoped to the stable aliases and existing `v1` collections. The indexer adds the
new filter fields to the existing collections and preserves the stable aliases.
Typesense search analytics is enabled on the retained search volume at
`/data/analytics` and flushes every 60 seconds; the private admin API presents
popular and no-result queries through the Search analytics page.

If rollback is needed, revert this release commit through Git so application images
and the migration-hook pin return together. Preserve database contents, search
credentials, aliases and PVCs; do not roll back the database below schema `0017`
without a coordinated downgrade plan.
