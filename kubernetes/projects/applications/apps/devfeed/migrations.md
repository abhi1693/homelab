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

Migrations must be compatible with the currently running release because they
run before its replacement. The v0.0.8 schema change was applied only after old
pods retired; subsequent upgrades now start from schema 0006. Use an earlier
compatibility release when a future migration cannot safely precede deployment.

Validate manifests with a server dry run, then verify the Helm hook's successful
last-run result, disappearance of the successful Job, live schema revision and
index validity, Fleet convergence and application readiness. Keep retained PVCs,
credentials and content through upgrades and cleanup.

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
