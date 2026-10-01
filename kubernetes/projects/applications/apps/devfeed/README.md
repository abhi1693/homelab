# DevFeed

Fleet-managed developer news platform. All application workloads use release
**0.0.45** and verified ARM64 image digests. Approval and publication require an explicit article page-kind
classification; missing or uncertain classifications stay blocked.

Renovate tracks stable `X.Y.Z` Docker tags for all ten DevFeed images on GHCR,
grouping runtime, init-container, and migration-hook updates while refreshing
their SHA-256 pins. Commit tags, moving tags, and prereleases are excluded;
Kubernetes continues pulling the pinned images through Harbor.

Reader language preferences support one or more languages, defaulting to English.
My feed and Latest retain source/content filters and offer Most liked sorting.
Source/topic discovery is paginated and restricted to the selected article languages.
Web, Chrome and Edge share the reader; extension 0.1.15 store publication is separate.
Sources added by import, the admin form, or CLI share discovery and review. Imports
remain pending until reviewed; full-auto mode uses AI review and approval enables polling.
The pre-upgrade hook applies and verifies schema `0020` before replacing application workloads.
Release 0.0.41 applied migrations `0018` and `0019`; the migration job mounts the
operator-managed historical topic-kind map needed to canonicalize stored topic data.

Release 0.0.45 uses source `a206a06566bb272364f016a6a6f8ee19894ed105` and the
[verified release manifest](https://github.com/abhi1693/devfeed.tech/actions/runs/36775240970)
(`image-manifest-images-36775240970-1`). All ten ARM64 image indexes match
between GHCR and Harbor, with verified GitHub provenance attestations for the tag.
Migration `0020` adds managed topic logos and topic-targeted Images jobs. The
one-time topic-logo backfill hook has been removed from GitOps; future upgrades
do not enqueue a bulk backfill. The existing Images worker continues normal logo
processing, saving originals to R2 before generating 32/64/96 WebP variants.
The import phase saved 354 of 357 originals, including Rancher. Memcached, Zorin OS
and VxWorks SVGs were rejected by validation and use the normal topic fallback.
All 354 saved logos now have 32/64/96 variants; no topic-logo jobs remain queued
or running. The Images worker is restored to its normal single replica after
temporary backfill parallelism. Readers use the saved original during future
variant processing. Public image loading and browser canvas export were verified
before frontend cutover.
Public-read CORS on the image bucket is required for browser card exports. Also
configure a Cloudflare Response Header Transform Rule matching
`http.host eq "images.devfeed.tech"` to **Set static**
`Access-Control-Allow-Origin: *`. R2 omits CORS headers on requests without Origin;
the rule keeps ordinary image responses usable when Chrome reuses them for canvas
exports. Verify both ordinary and Origin-bearing responses, then exercise export
in a fresh browser session before reader cutover.

GitHub and Google provider IDs use `DEVFEED_OIDC_GITHUB_IDP_ID` and
`DEVFEED_OIDC_GOOGLE_IDP_ID` for both interfaces. Admin and reader retain their
separate OIDC application client IDs. Keep schema `0020` when rolling forward or
reverting to a compatible build; an image-only rollback to 0.0.43 is not supported.

| Entry point | Routing | OIDC client |
| --- | --- | --- |
| `https://devfeed.tech` | Public Cloudflare Tunnel, reader frontend only | `390346916430350165` |
| `https://admin.devfeed.home` | Internal Traefik, home-local-ca certificate | `390346721797867349` |

Search and topic Follow actions return to the originating page after sign-in;
search queries and filters survive the callback. Return URLs remain restricted
to known local paths and search parameters.

The reader sign-in page offers GitHub and Google through the existing Zitadel
client. Both APIs load the `devfeed-oidc-providers` ConfigMap, selecting GitHub provider `390412503718298452`
and Google provider `391210575599764264`. Changing these IDs requires rolling the
reader and admin APIs via their `devfeed.tech/oidc-providers` pod-template annotations.

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
- **One dedicated worker each** for ingestion, source discovery, source enrichment,
  article enrichment, and image processing. The obsolete background deployment and its disruption
  budget have been removed; each category has its own consumers.
- **Three dedicated article-analysis workers** and **one each** for topic analysis, source analysis,
  research verification and relationships, plus **one pooled AI worker** for legacy
  deliveries and additional fair queue coverage. Eight AI consumers retain shared
  provider cooldowns; topic workers are reduced from three to one.
- One scheduler publishes each physical queue with its own dispatch budget.
  Its health thread renews the 120-second heartbeat every 20 seconds during long
  cycles, but stops renewal after five minutes without a successful cycle. It also
  refreshes quota independently of dispatch work. The scheduler requests 500m CPU;
  its liveness probe allows 15 seconds for Python startup and Redis discovery.
- **One dedicated notification worker** prevents delivery starvation while
  extraction workers process article pages.
- The busiest worker pods (article analysis/enrichment, ingestion, images and
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

## AI model recovery (2026-09-26)

On September 26, production used `gpt-5.6-luna` for fast analysis and research,
and `gpt-5.6-terra` for the baseline and escalation routes. The production ChatGPT
account rejected `gpt-6-luna`; its fresh Codex model catalog also omitted
`gpt-6-sol`. Validate all route models against the production account catalog
and successful inference before changing these settings. Account readiness alone
does not prove model access. The `devfeed.tech/ai-models` pod-template annotation
rolls all automation ConfigMap consumers when the model configuration changes.
On September 27, the production account catalog included `gpt-6-luna` and
`gpt-6-astra`, and both completed structured-output inference through the deployed
Codex app-server. Production now uses **GPT-6 Luna** for fast analysis (low effort)
and research (medium effort), and **GPT-6 Astra** for baseline and escalation
(medium effort on escalation). The model annotation rolls every automation
ConfigMap consumer; quota pacing and provider cooldowns remain unchanged.
Roll back the model-selection commit through Fleet if access regresses.

The one-time `devfeed-requeue-articles-20260926` Job completed at 11:59:50 UTC
on September 26: 1,187 fresh analysis jobs and 52 enrichment requests covered all
1,239 selected pending/latest-failed unpublished articles discovered before
11:41:46 UTC. Published articles, editorial rejections, and failure history were
preserved. The existing scheduler controls dispatch and quota pacing; completion
of the recovery Job means work was queued, not that every article was analyzed.
The recovery manifest is retained in Git commit `15282ac7` and removed from the
active Kustomization after completion. Fleet may retain the completed Job as an
audit record. Analysis jobs carry `usage.recovery_id = models-2026-09-26`.

## Article requeue (2026-09-27)

The one-time `devfeed-requeue-articles-20260927` Job requeued articles discovered
by `2026-09-26T20:53:28.753724Z` that are still unpublished and not rejected.
It rechecks those states under each article lock, reuses active work, and sends
articles without usable text through enrichment first. Articles without an
approved source stay blocked. Existing editorial decisions and job history are
preserved; normal scheduler quotas and cooldowns govern processing.
New analysis jobs carry `usage.recovery_id = articles-2026-09-27-gpt6` so retries
cannot create duplicate analyses. The job requires the verified GPT-6 routing
configuration. It completed at `2026-09-26T21:13:22Z`, checking 634 articles:
535 new analysis jobs, 52 enrichment requests, 40 active analyses reused,
five articles skipped after becoming published/rejected, and two blocked because
they had no approved source. Completion means the work was queued; downstream
processing continues under normal pacing. The recovery manifest is retained in
Git commit `dd38f6e3` and removed from the active bundle to prevent future runs.
Fleet removed the completed Kubernetes Job during retirement; the completion
totals above and Git history retain the audit record.

## Published article image recovery (2026-09-26)

The one-time `devfeed-requeue-images-20260926` Job requests image discovery for
published articles without an `image_url` at the 12:04:38 UTC cutoff. Previous
failures and `not_found` outcomes are eligible; active work is preserved. The Job
uses `request_image` in batches of 100 and marks new discovery jobs with
`storage.recovery_id = published-images-2026-09-26` for retry safety. It does not
change publication state or overwrite existing images. The existing scheduler,
image workers, solver, and managed-image storage process the requests normally.
The Job completed at 12:11:15 UTC: all 8,653 selected articles received a fresh
image-discovery job, with no skips. The manifest is retained in Git commit
`b0a23e89` and removed from active GitOps configuration. Queueing completion does
not imply every publisher page provides a discoverable image.

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
The indexer publishes a local heartbeat after successful batches. Startup,
readiness, and liveness check its file modification time against the 120-second
deadline, avoiding an empty-string parse while the writer truncates and rewrites
the file. Missing, stale, or future-dated files fail the probe. Public search uses
only `documents:search` credentials, while the indexer and
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

DevFeed 0.0.45 replaces the retired aggregate exporter with native OpenTelemetry
in-process metrics on APIs, workers, scheduler and indexer. Frontends retain their
Node metrics. The PodMonitor sets a consistent `service` label from each workload;
HTTP recording rules normalize Node and Python histograms and exclude long-lived
notification streams. Metrics stay private on port 9100, with no public ingress.

The **DevFeed** Grafana folder replaces all three dashboards in place, retaining
stable URLs: availability/capacity, workers/search progress, and request/cache/
database/log diagnostics. Retired queue/product aggregate panels and their alerts
are removed. Use the admin UI for durable job outcomes, retries and editorial
inventory; worker delivery counts do not imply editorial success. Current alerts
cover traffic-gated availability burn, latency, workload readiness, scrape health,
database acquisition timeouts, background freshness and search lag.

Alloy/Loki, OTel/Tempo and Pyroscope continue collecting logs, traces and profiles.
Logs and Faro browser telemetry preserve original values without automatic
redaction. Frontends alone consume the encrypted Faro collector key. Private
blackbox probes continue checking public HTTPS and internal service readiness.

Run `python3 scripts/check-devfeed-observability.py` to validate dashboard PromQL
and alert scenarios, followed by manifest checks and server-side dry runs. Metric
names and migration details are documented in the application's
[Observability guide](https://github.com/abhi1693/devfeed.tech/blob/v0.0.45/packages/core/OBSERVABILITY.md).

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

The dedicated Images worker downloads originals through the application's SSRF-safe
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
retries. Topic logos share this durable pipeline as of 0.0.44, using normalized PNG
masters under `originals/topic-logos/` and WebP variants under `topic-logos/`.
The saved original is served while variants are unavailable. Source logos remain
outside the managed-image pipeline. Existing source URLs stay available for editing
and provenance; readers receive only owned topic-logo URLs.

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

### 0.0.41 release verification and rollback

The six application image references and migration hook come from the successful
`v0.0.41` CI image manifest at revision `b8748c09740f7d12438d399ad7b12d25b608ad9d`.
Revision `0018` adds profile and reading-streak data. Revision `0019` maps historical
topic kinds using `devfeed-topic-kind-map` before enforcing canonical values; review
that operator map against current stored kinds before each deployment. Verify Harbor
digest parity, Fleet desired/applied equality, ready replicas, schema `0019`,
profile pages, and reader behavior. Extension ZIPs are version `0.1.11`; browser
store publication is separate.

If rollback is needed, revert the release commit through Git so image pins and the
migration hook move together. Preserve database contents and do not roll back below
schema `0019` without a coordinated downgrade plan.

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

## Topic logo restoration (2026-09-27)

The one-time `devfeed-restore-topic-logos-20260927-v2` Job restores the official
standalone color icons for Kubernetes and Rancher. It uses audited update
proposals and the existing review service, preserving topic identity, kind and
other metadata. It fills Rancher's missing official website as well. Existing
logos or pending edits block replacement; retries recognize already applied URLs.
The Job uses the immutable 0.0.42 backend and remains in Git history after retirement.

Kubernetes artwork is pinned to CNCF artwork commit
`831f27a0cf4227b1b76a28ff51a9f4127a2195ec`; Rancher uses the cow icon linked from
<https://www.rancher.com/brand-guidelines>. Both direct SVGs returned HTTP 200 and
`image/svg+xml` before rollout. Automatic branding enrichment for all kinds is a
separate application change and is not enabled by this restoration.

The initial Job failed validation before commit because the review payload omitted
the full draft; its transaction rolled back. The v2 Job supplies the reviewed draft.

The v2 Job completed successfully. Public API reads confirm both platform logos
and Rancher's official website. Audit proposal IDs are
`ea947f06-b60e-474d-865e-f8365974d919` (Kubernetes) and
`bda360d6-42e5-4ce5-ac69-5e1bef398d0e` (Rancher). The completed Job is retired
from desired state; its manifest and input evidence remain in Git history.

## Agent connections

Two ARM64 MCP replicas serve `https://mcp.devfeed.tech/mcp` through the Cloudflare
tunnel. Public discovery calls only the public API. OAuth account tools call the
user API through the private `user-api` Service alias and share its Redis database 10; MCP has no database or admin credentials.
The reader advertises this endpoint, offers read-only/read-write consent and lists
revocable connections. MCP egress is restricted to DNS, Redis and the two APIs.
