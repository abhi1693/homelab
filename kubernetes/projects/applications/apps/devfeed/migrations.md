# DevFeed migration lifecycle

`migration-hook.yaml` is the single ongoing schema upgrade Job. Fleet invokes
Helm upgrades; Helm runs this `pre-upgrade` hook at weight -10 before replacing
application resources and waits for success. The immutable backend image must
match the application release. Migration failure blocks the upgrade.

`before-hook-creation,hook-succeeded` removes previous attempts before a retry and
cleans successful Jobs automatically. Failed hook Jobs remain for diagnosis.
Do not edit Helm release secrets or manually replay a running migration.

The hook uses existing configuration, database credentials and the `devfeed`
service account. A new environment must provision those dependencies, schema and
inbox credentials before installing the application. Historical production Job
manifests are not a supported initial-install procedure.

Hooks run before workload replacement. Drain incompatible background processes
through earlier Fleet revisions before migration; API readiness can briefly drop
until the matching replacement services start. Use an earlier compatibility
release when a migration cannot safely precede deployment.

Validate manifests with a server dry run, then verify the Helm hook's successful
last-run result, disappearance of the successful Job, live schema revision and
index validity, Fleet convergence and application readiness. Keep retained PVCs,
credentials and content through upgrades and cleanup.

## Release 0.1.2: schema 0034

Follow the [phased read-model cutover](read-model-rollout.md). The additive
migration installs transactional capture, projections and saved reports; its
two standard review indexes briefly block review writes. A separate pre-upgrade
hook initially builds the pipeline and default reports. After current-policy
pipeline completion is proved, retire that one-time hook to restore core API
availability while durable publishers finish reports. All 27 fresh current-policy
reports remain mandatory before queue resume, worker restoration or publication.
Reserve publisher database capacity and quiesce existing
background writers first. Previous 0.1.1 applications reject schema `0034`, so
readiness drops across this explicit maintenance boundary. Preserve the schema
and roll forward with compatible images; no historical recovery replay is part
of this rollout.

## Release 0.1.1: schema 0033

The matching backend hook applies migrations `0027` through `0033`: processing-history
indexes, transactional search-visibility revisions, topic-history range indexes,
daily inference totals, separate source profile/relevance operations, and article
lifecycle indexes. Migration `0031` backfills exact totals while holding a ledger
write lock. Migration `0033` builds indexes concurrently and repairs interrupted
index builds on retry. Verify a successful CNPG backup and healthy WAL archiving
before starting the rollout.

Use separate Fleet revisions to preserve the drain order:

1. Set scheduler replicas to zero, wait for Fleet convergence and its pod to exit,
   then drain active RQ deliveries. Durable queued outbox requests can remain for
   the new scheduler. Inspect job status instead of treating orphan intermediate
   queue entries as active work.
2. Set the thirteen worker Deployments and search indexer to zero and wait for old
   pods to exit. Include the shared AI worker, which also consumes source analysis.
   Older coupled source consumers must not receive the split operations from `0032`.
3. Update every runtime, init-container, and migration image to the verified release
   pins and restore worker/indexer replicas, keeping the scheduler stopped. The
   pre-upgrade hook must complete before replacement workloads start.
4. Verify schema `0033`, valid indexes, all replacement images and readiness, then
   restore the scheduler through Fleet and verify desired/applied equality again.

Release 0.1.1 also accepts schema `0032` during a forward rollout; earlier schemas
lack required source-processing fields. The hook retains the 600-second statement
budget, 30-second lock budget, and 840-second deadline. Migration `0033` bounds its
index metadata locks to five seconds. Deploy APIs and the reader before publishing
extension 0.1.22. Preserve schema and processing evidence for recovery; an image-only
rollback to 0.1.0 is incompatible, and downgrading `0032` is guarded while split work
or explicit processing requests remain.

## Release 0.1.0: schema 0026

The matching backend pre-upgrade hook applies `0024` (partnerships), `0025`
(adaptive source polling), and `0026` (saved tag follows) before replacing workloads.
Verify a successful CNPG backup before rollout, migration completion, schema `0026`,
all replacement pods Ready, and Fleet desired/applied equality. Migration `0024`
backfills matching vocabulary; existing sources default to fixed polling in `0025`.
The production article-token backfill exceeds the normal 30-second query budget.
The hook appends a process-local connection listener with `statement_timeout=600s`
and `lock_timeout=30s`, after the application default listener. Normal services
retain the 30-second budget. The Job permits one retry and has an 840-second deadline
within Fleet’s 900-second Helm timeout. The failed initial backfill rolled back.

Enable the shared adaptive gate and partner signing/encryption configuration with the
new images. Deploy the APIs before distributing extension 0.1.21.

Preserve the upgraded schema and recover using schema-compatible images. Downgrading
partnership tables destroys catalog, campaign, matching, and attribution records.

## Release 0.0.52: schema 0023

Apply `0023` with the matching backend pre-upgrade hook. It adds `sources.managed_logo`,
the nullable image-job source reference, source-job indexes, and a subject constraint
that supports managed publisher logos. Existing accounts, articles, bookmarks, topic
logos, and preferences are retained. The existing Images worker processes source logos
using its configured R2 storage and imgproxy connection.

Verify a completed offsite PostgreSQL backup and healthy WAL archiving before the
upgrade. Older 0.0.51 services require schema `0022`, so readiness can briefly drop
after migration until replacement pods start. Preserve schema `0023` and recover with
compatible images through Fleet; do not run the destructive downgrade as part of an
ordinary image rollback.

Verify schema `0023`, both new columns, valid source-job indexes, successful hook
completion, matching Fleet deployment IDs, all release image pins, API readiness,
and scheduler-generated sitemap snapshots.

## Release 0.0.51: schema 0022

Apply `0021` (persisted daily Must Reads) and `0022` (topic description vocabulary
in ranking revisions) with the matching backend pre-upgrade hook. These migrations
retain existing accounts, articles, bookmarks and preferences. The revision trigger
invalidates old topic ranking snapshots after the upgrade.

Older 0.0.50 services require schema `0020`, so readiness can briefly drop before
replacement pods start. Keep schema `0022` and recover with compatible images;
an image-only rollback to 0.0.50 is insufficient. Do not drop saved daily picks
or downgrade the database as part of an ordinary image rollback.

Verify schema `0022`, the `user_must_reads` table, the description-aware
`refresh_topics_revision()` function, valid indexes, successful hook completion,
matching Fleet deployment IDs, release image digests, and reader/API readiness.

## v0.0.9

The v0.0.9 backend hook upgrades `0006` through `0007` (private bookmarks) to
`0008` (inference calls). Both migrations add tables and indexes without changing
existing article data. Older API readiness rejects schema `0008`; a brief service
interruption is possible until the new pods become ready. New pods require `0008`.
Do not roll back only the images to v0.0.8; prefer a compatible forward fix.
After Fleet convergence, verify the successful hook record and cleanup before the
separately authorized rejected-article reset. Preserve all historical reviews.

## v0.0.10

Schema `0009` adds `topic_decision_runs` and its indexes. The pre-upgrade hook
uses the v0.0.10 backend and cleans up on success. Existing v0.0.9 APIs reject
revision `0009` until replaced; a brief readiness interruption is possible.
Keep the new schema and roll forward with compatible images if recovery is needed.
No rejected-article reset is part of this release; the v0.0.9 reset remains audited.

## v0.0.11

The corrected backend retains schema `0009`. Its pre-upgrade hook verifies the
current head and still cleans up automatically. v0.0.10 and v0.0.11 backends
accept the same schema, so this correction has no schema compatibility gap.
Topic canary recovery uses explicit budget grants after live validation, preserving
all previous charges and decisions; it is separate from schema migration.


## v0.0.19

Schema `0010` adds source-discovery candidates, provenance, feed evidence, and durable
jobs. Pending sources may have no feed while discovery runs; approved sources must
retain a feed. Existing source decisions, accounts, articles, and preferences are
preserved. The backend image in the pre-upgrade hook matches all application pins.

Older application readiness requires `0009`, so a brief interruption is possible
between migration and workload replacement. Verify hook success, schema `0010`,
source counts, Fleet convergence, and API/reader behavior after rollout. Keep the
new schema and use a compatible forward fix if recovery is needed; an image-only
rollback to `v0.0.18` is not compatible with the new schema.


## v0.0.20

Schema `0010` is unchanged. The v0.0.20 backend hook verifies the existing head
before replacing services. Article-analysis capacity increases to three dedicated
workers. Shared weekly-quota pacing is enabled with a 20% reserve; the scheduler
must refresh quota before AI admission resumes. Verify a fresh quota snapshot,
worker readiness and completed work after Fleet convergence.

## v0.0.21

Schema `0011` adds the nullable `articles.ai_title` column while preserving source
titles and existing editorial decisions. The matching backend migration hook runs
before workload replacement. Older APIs require `0010`, so a brief readiness
interruption is possible. Verify hook success, schema `0011`, Fleet convergence,
all release images and reader behavior. Do not reanalyze existing articles as part
of this rollout; selective reanalysis is a separate operator action. Keep the new
schema and use a compatible forward fix if recovery is needed.

## v0.0.22

Apply `0012` (recommendation candidate rebuild tracking) and `0013` (managed article
image metadata and durable Images storage progress) with the matching backend hook.
Existing content and preferences are retained. Redis holds expiring shuffled feed
generations; a Redis outage falls back to the database without shuffling.
Older services reject schema `0013`, so readiness can briefly drop before their
replacement. Verify migration, Fleet convergence, release digests, reader behavior
and an image storage operation. Recover with schema-compatible images rather than
an image-only rollback to v0.0.21. R2 backfill is independent of the schema migration.

## Release 0.0.24: schema 0014

The pre-upgrade hook adds nullable `inputs_pruned_at` markers to article and topic
analysis jobs, then creates active-topic and successful-job retention indexes
concurrently. The migration preserves current payloads and publication decisions.
Before retrying an interrupted migration, inspect `pg_index.indisvalid`; invalid
release indexes require an explicitly authorized repair.

Verify schema 0014, successful hook completion, matching Fleet deployment IDs and
all new application images before declaring the rollout complete. Older 0.0.23
services require schema 0013, so a readiness gap is possible. Keep schema 0014 and
recover with compatible images; an image-only rollback is insufficient.
