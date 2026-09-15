# DevFeed v0.0.8 worker capacity

Read-only production assessment on 2026-09-13 at 09:58 UTC, before deployment.
The database queries used read-only transactions and four-second statement limits.
Counts describe durable application jobs, not RQ transport success.

| Work | Due backlog | Arrivals/hour | Successful completions/hour | Previous workers | Release workers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Article analysis (before cutoff) | 1,538 | 633 | 573 | 3 | 1 dedicated, plus shared help |
| Topic analysis | 1 | 258 | 258 | 3 | 3 |
| Relationship research | 2 | 241 | 242 | 3 | 3 |
| Research verification | 3 | 391 | 393 | 3 | 3 |
| Source analysis | 0 | 0 | 0 | 3 | 0 dedicated; shared pool |
| General ingestion/enrichment/images | 3 | 257 | 254 | 5 | 2 |
| Notifications | 4 | 998 | 998 | 1 | 1 |
| Browser-challenged solver work | 0 | 0 | 0 | 1 | 1 |
| Shared AI pool | — | — | — | 0 | 1 |

The pooled worker uses the existing `analysis` group, which round-robins all AI
queues, including infrequent source work and legacy deliveries. It receives no
notification credentials. General workers also support enabled notifications.
Keep the separate solver because its remote-browser configuration cannot be shared
with ordinary consumers. Total workers decrease from 22 to 15; AI concurrency
decreases from 15 to 11. Three idle source consumers are replaced by one useful
shared consumer, article replicas decrease to one after applying the source-date
cutoff, and background replicas decrease to two. Requests decrease by 700m CPU
and 1,792Mi memory.

Source analysis completed only one job in three hours. General-worker logs show
250 feed ingestions using 516 worker-seconds, 49 seconds of language detection,
and one two-second article enrichment in the requested last-hour window. Log
rotation can shorten retained windows, so these are observed work samples, not
an exact utilization percentage. Two general workers preserve burst headroom.
Recent topic, relationship, and verification jobs averaged approximately 31, 32,
and 27 seconds of recorded cumulative inference time; those pools are actively
needed. Verification runtime is only available for 611 of 1,016 recent completions.

## Drain-time estimate and limits

The user subsequently selected a default source publication cutoff of September 1,
2026. A second read-only snapshot found **94 eligible queued articles**, versus
1,194 older and 156 undated queued articles. Eligible arrivals were 26 in one hour
and 126 in three hours (42/hour). There were 128 eligible pending unpublished
articles, compared with 1,508 older and 185 undated articles. Queue/discovery time
is never used as a fallback for source publication time.

One dedicated article worker at the previous observed 191 completions/hour leaves
149/hour after the higher eligible arrival estimate: the 94-job queue projects to
about 38 minutes. Even at half that service rate, net capacity remains positive
and the estimate is under two hours. Shared AI help is additional headroom. These
are planning estimates based on mixed-content historical runtimes; validate the
actual eligible workload after deployment rather than assuming linear scaling.
The earlier five-worker estimate applied to the full pre-cutoff backlog and is
superseded. Moving the cutoff earlier or disabling it must trigger a new capacity
assessment before restarting a large historical backlog.

There are also 466 pending topic-reanalysis scans, 44 relationship scans, and
1,898 unpublished articles awaiting review/automation in the earlier snapshot. These are upstream work,
not additional ready inference jobs. The scheduler currently examines 50 articles
per reanalysis step, and completed three scans while creating 62 in the preceding
hour. A queue-only estimate therefore does not promise full catalog convergence.
The cutoff reduces each scan to the eligible publication window. As article publication
reduces that set further, scans become cheaper; track both
unfinished scans and pending articles after rollout. Do not add workers to fix a
scheduler-limited scan rate without inspecting that bottleneck.

Codex initially reported 65% weekly usage and no active shared cooldown. A follow-up
at approximately 10:27 UTC reported 67% used and 33% remaining while the previous
release continued processing the unrestricted backlog.
The reset is 2026-09-19 22:01:02 UTC. Remaining quota is not a guaranteed job count.
The plan reduces AI concurrency and removes older content from inference demand. The
database snapshot had 14 idle sessions, one active lock waiter, one active query,
and one idle transaction; there was no evidence of connection saturation. Node CPU
was 15–45% and memory 37–62% in the instantaneous preflight sample.

## Acceptance and adjustment

After deployment, verify all enabled queues have registered consumers, publication
and durable completions continue, and the article backlog decreases. Recompute
net drain time from observed deltas after the rollout settles; include new arrivals
and upstream scan counts. Review again after 30–60 minutes and when the backlog
clears. If net article drain is nonpositive, or projected drain exceeds 24 hours,
inspect provider cooldown/quota, retries, and scheduler/database limits before
adding capacity. If provider headroom allows and workers remain busy, temporarily
increase article consumers through GitOps. Reduce dedicated article replicas to
the measured steady-state requirement after the queue clears; retain the pooled
consumer for burst handling and source/legacy queue coverage.

Do not flush queues, replay running leases, or bypass publication approval gates.

## Observed rollout result

At 11:12 UTC, all 15 workers were registered under `devfeed-worker-<type>`,
with a consumer for every physical queue. From 10:56:35 to 11:12:43, eligible
queued article jobs decreased from 60 to 43 while one remained running. The
observed net reduction projects the remaining eligible queue to about 41 minutes
at the same rate. This short window includes the worker rename and is an
estimate, not a completion guarantee.

Since 10:54 UTC, 28 article results were applied against 10 new eligible jobs.
Topic analysis completed 168 jobs, verification 130, ingestion 92 and notifications
160, with no terminal failures in those four samples. No new older or undated
article-analysis jobs were created or applied in that window. Since the rollout
started, 787 older and 113 undated jobs were deferred; 859 had zero attempts and
41 retained attempts from before deferral. Deferral does not reset that history.

The provider reported 70% weekly usage at approximately 11:04 UTC, leaving 30%.
Keep the current 15-worker capacity while the eligible backlog drains; there is
no evidence here requiring additional workers. The retired historical backlog
continues draining through inexpensive date checks without AI inference.

All 29 application runtime pods were ready with zero restarts and verified
v0.0.8 digests after the rename. Fleet desired/applied IDs matched for DevFeed
and all affected collector/database-policy bundles. Schema 0006 and all twelve
new indexes were valid. Database, Redis and Codex exporter snapshots succeeded;
the measured database snapshot took 1.34 seconds. Public reader/search and
internal admin login returned HTTP 200. Private metrics and a source map returned
200; public metrics and source-map requests returned 404. Tempo traces, Loki
worker logs, Python/Node profiles and reader/admin Faro receiver delivery were
verified. Faro delivery used anonymous synthetic events, not a full browser
journey.

The Helm pre-upgrade hook succeeded in release revision 33 at 11:13 UTC and
automatically removed its Job. Historical migration and completed inbox bootstrap
Job manifests, and the temporary separate migration bundle, were removed.
