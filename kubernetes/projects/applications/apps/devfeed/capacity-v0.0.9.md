# DevFeed v0.0.9 worker capacity

Production read-only assessment on 2026-09-13, approximately 16:16 UTC.
Queries used read-only transactions and four-second statement timeouts.

| Work | Due | Running | Arrivals/hour | Completed/hour | Release capacity |
| --- | ---: | ---: | ---: | ---: | --- |
| Article analysis | 0 | 0 | 0 | 0 | One dedicated worker plus shared AI pool |
| Topic/relationship research | 1 | 5 | 607 | 606 | Three topic and three relationship workers |
| Research verification | 0 | 2 | 477 | 478 | Three workers |
| Source analysis | 0 | 0 | 0 | 0 | Shared AI pool; dedicated replicas 0 |
| Ingestion/enrichment/images | 0 | 0 | 0 | 0 | Two background workers |
| Notifications | 1 | 0 | 489 | 490 | One dedicated worker, background assistance |

The shared AI worker consumes all AI queues and remains at one replica. Topic and
relationship jobs share one database table, so the combined row must not be counted
as two independent workloads. Redis corroborated one waiting topic job and zero
other AI queue depth. There is no current article backlog, including deferred jobs.
All 132 sources already use twelve-hour polling, explaining the quiet ingestion
window; retain two background consumers for scheduled feed bursts. Retain the
separately configured browser solver because background workers cannot handle its
browser-challenge work.

The initial empty-backlog assessment would have removed the dedicated article
consumer. The user subsequently requested resetting all rejected articles after
v0.0.9 becomes healthy. A new snapshot found 4,779 rejected articles: 381 eligible
under the September 1 source-publication cutoff, 4,118 older and 280 undated.
Retain the existing dedicated article worker for that newly authorized workload,
keeping 15 total workers and 11 AI consumers. Dedicated source replicas remain
zero. Every queue retains coverage without adding workers for idle types.

The earlier measured article service rate was approximately 191/hour; using a
conservative half-rate of 95/hour, 381 articles would take about four hours without
new arrivals, or seven hours with the earlier 42/hour arrival estimate. These are
planning estimates, not promises: some articles may lack text, require research,
be rejected again, or wait for provider quota. Older and undated content returns
to pending but remains excluded from AI inference. Preserve rejection history and
increment editorial revisions; do not overwrite previous model results.
Topic/verification completion rates track arrivals, so retain their capacity.

Reassess after the next feed polling burst or a cutoff change. If eligible article
backlog is growing, compare arrivals/completions over 30–60 minutes and calculate
`queued / (completions/hour - arrivals/hour)`. Increase article capacity
through GitOps if projected drain exceeds 24 hours and provider headroom permits;
inspect quota, scheduler and retries before adding capacity. Once the eligible reset backlog clears, reassess removing
the dedicated article worker in favor of the shared pool. Historical failed jobs
and unpublished editorial backlog are not equivalent to ready inference jobs.

The release retains production model routing. Gemini/OpenRouter adapters are local
benchmark tooling; no new provider credentials or fallback routing are deployed.
