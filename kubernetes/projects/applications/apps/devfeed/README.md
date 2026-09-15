# DevFeed

Fleet-managed developer news platform. All six application images use `v0.0.20`.
Sources added by import, the admin form, or CLI share discovery and review. Imports
remain pending until reviewed; full-auto mode uses AI review and approval enables polling.
The pre-upgrade hook applies schema `0010` before replacing application workloads.

| Entry point | Routing | OIDC client |
| --- | --- | --- |
| `https://devfeed.tech` | Public Cloudflare Tunnel, reader frontend only | `390346916430350165` |
| `https://admin.devfeed.home` | Internal Traefik, home-local-ca certificate | `390346721797867349` |

Search and topic Follow actions return to the originating page after sign-in;
search queries and filters survive the callback. Return URLs remain restricted
to known local paths and search parameters.

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
- **One dedicated worker each** for ingestion, article enrichment, source enrichment
  and images. The former background pool is scaled to zero, so slow jobs in one
  category no longer occupy every consumer of another category.
- **Three dedicated article-analysis workers** and **one each** for topic analysis, source analysis,
  research verification and relationships, plus **one pooled AI worker** for legacy
  deliveries and additional fair queue coverage. Eight AI consumers retain shared
  provider cooldowns; topic workers are reduced from three to one.
- One scheduler publishes each physical queue with its own dispatch budget.
- **One dedicated notification worker** prevents delivery starvation while
  extraction workers process article pages. See [September 14 capacity review](capacity-2026-09-14.md).
- **One solver worker** consumes browser-challenged enrichment jobs, using the
  existing remote browser service in `media` without installing browsers in workers.
- **One Typesense 30.2 instance and one dedicated search indexer** serve federated
  article/topic/source/tag search. Typesense is internal-only with a retained 10Gi
  Longhorn volume; the API receives only its restricted query key.
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
on its retained 5Gi Longhorn home.

On an empty Codex volume, the `chatgpt-login` init container runs device sign-in.
Read its logs and complete the displayed browser authorization. This is a separate
ChatGPT sign-in, never a copy of local or Wardn Hub credentials. Restarts reuse
existing sign-in state. If sign-in is incomplete, the pod waits before starting
Codex; analysis workers wait for account readiness.

## Data and secrets

The shared CloudNativePG bundle owns retained `devfeed` and `devfeed_chimely`
databases and roles. Two `devfeed-rw` session poolers provide up to 20 backend
connections per database; each role allows 24. App SQLAlchemy pools are bounded to
one connection per web/API process with no overflow. Workers and the scheduler
use `DEVFEED_DATABASE_POOL_ENABLED=false`, returning idle connections to the
external session pooler instead of reserving slots while doing network work.
Release `v0.0.6` bounds connection failure detection with TCP keepalives and an
8-second TCP user timeout; API pool acquisition waits at most two seconds.

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
1Gi NFS volume. Only the background and dedicated notification workers receive delivery keys. Admin/user APIs
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
queue/worker/product and diagnostics dashboards. Two private blackbox exporter pods
probe the public reader and internal service readiness/login every 30 seconds.
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

Worker deployments use `devfeed-worker-<type>`, including `background` and `ai`
for shared pools. Replica counts and queue subscriptions are unchanged by naming.

The workload catalog mirrors the dedicated worker replica counts, including the
four background pipeline consumers, so capacity recommendations use the same intent.

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
origin. Extension analytics remains disabled until separately configured with
its own GA4 property and server-only secret. Store submission is independent
of the application rollout.
