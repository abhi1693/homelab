# DevFeed queue maintenance validation

This release-specific helper prepares the `0.1.1` / schema `0033` workers for the
`0.1.2` / schema `0034` cutover. Installation and every live state change go
through Fleet. Run neither the controller nor its fixture against production
from an operator shell.

The controller owns a bounded RQ pause, requests one normal warm shutdown attempt
per original worker, and waits for supervised replacements to suspend. A solver
bridge lets already-running producers finish synchronous solver requests. It
starts consuming only after the original solver has finished and its replacement
has suspended, preserving the single solver-consumer boundary. Ordinary queued
work remains in place. Completion requires empty execution/intermediate registries
and a fully exited bridge. Inspect actual Pod/container transitions before the
next Fleet revision scales suspended workers to zero.

The pause is global to Redis DB10. The approved scope binds all fifteen worker
Pods and their queue roles, the three article-analysis replicas, and narrowly
identified historical metadata. Refuse foreign workers, changed metadata,
pre-existing pauses, missing ownership, incomplete execution evidence and unsafe
timeouts. An at-most-one publish-attempt ledger prevents blind retries; Redis
PubSub does not guarantee delivery. Failures retain the pause. Use an explicit
reviewed recovery Job to resume the same owner before cutover, or the new-image
resume Job after the schema and read-model gates pass.

The [native validation workflow](../../.github/workflows/devfeed-maintenance.yml)
pulls the exact deployed ARM64 backend index, verifies its resolved config,
source/version and RQ/module hashes, and runs real workers with disposable Redis
DB15 over a private Unix socket. Containers have no network, credentials or
production mounts; they use UID10001, read-only roots, dropped capabilities,
finite resources and owned temporary storage. Fixture PostgreSQL context is
explicitly injected; it does not prove the production schema check. Deployment
still requires the actual runtime/schema guard and a fresh live scope check.

The regression harness checks current-job completion, synchronous dependency
handoff, suspended replacements and backlog preservation. Negative cases check
duplicate/ambiguous warm attempts, existing shutdown requests, foreign scope,
owner/TTL loss and explicit recovery. The workflow retains sanitized JSON evidence
with named wait boundaries and aggregate process/transport states on failure,
and removes only its own fixture containers and volume. The dependency regression
delays release before enqueue, then holds the real solver beyond the earlier
release deadline to verify that each phase has its own bounded budget. The cleanup
fault waits for the held solver function to acknowledge entry, rather than merely
observing RQ's earlier current-job pointer. Actual worker barriers also hold both
native replacement startup states and force registration changes across snapshot
reads. Initial admission refuses startup states; owned replacements remain pending
until they report suspended. Local x86 execution is
development evidence; require the hosted ARM64 result before installing the Job.

For focused debugging in the same isolated, empty DB15 fixture, the harness accepts
`--case dependency-budget`, `--case worker-snapshot`, or `--case controller-fault`.
Evidence identifies the selected case; only the default `--case all` validates
the complete suite. Original workers bootstrap before jobs are enqueued, keeping
setup time outside the jobs' bounded release and dependency waits.

Follow the [phased rollout](../../kubernetes/projects/applications/apps/devfeed/read-model-rollout.md)
for database reservation, worker drain, migration, backfill, image verification,
owned resume and the subsequent ordinary-work observation period.
