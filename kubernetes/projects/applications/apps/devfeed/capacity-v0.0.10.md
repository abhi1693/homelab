# v0.0.10 worker capacity

This historical assessment is superseded by the dedicated per-category workers in [README](README.md).
Read-only production sample: September 13, 2026, 17:37–17:39 UTC. All 15 RQ
workers had current heartbeats. Article analysis had 153 due queued jobs (oldest
about an hour) and two running jobs; 249 succeeded during the preceding hour.
At that observed rate the queued work represented about 37 minutes of processing,
excluding new arrivals. This was a capacity allocation problem, not absent consumers.
Three relationship workers were busy while three verification workers were idle
at the sample. These instantaneous observations are not utilization averages.

| Role | v0.0.9 | v0.0.10 | Reason |
| --- | ---: | ---: | --- |
| Article analysis | 1 | 1 | Remaining cohort is already draining; shared pool assists |
| Topic decisions | 3 | 3 | Prioritize actual approvals/rejections |
| Legacy verification | 3 | 0 | Shared pool drains the small remaining queue |
| Relationships | 3 | 0 | Paused while actionable topics remain; pool covers later demand |
| Shared AI | 1 | 1 | Fair round-robin across physical AI queues, including source work |
| Source analysis | 0 | 0 | Covered by the shared pool |
| Background | 2 | 2 | Ingestion, enrichment, images and notifications |
| Notifications | 1 | 0 | Background consumers suffice for currently empty queue |
| Solver | 1 | 1 | Browser-challenged enrichment uses its separate queue/security boundary |
| **Total RQ workers** | **15** | **8** | **Five AI consumers, down from eleven** |

A later sample at 18:08 UTC found 35 queued article jobs, down from 153 without
scaling, with 62 completions in 15 minutes. Only one verification job was queued
and one running. The earlier proposed increase to three article consumers is
therefore unnecessary. One dedicated article consumer and the pooled worker cover
remaining/new article demand; the pool also covers legacy verification fairly.

This does not assume more workers create model quota. Bounded topic reviews use
Luna for normal work, reusable evidence and at most one Terra correction. Admission
starts at one topic decision, then increases to four after live inspection.
Relationship work has zero dedicated replicas and a shared rolling daily allowance
after the actionable topic backlog clears. Deferred topics remain explicitly visible
for manual review or audited budget grants; they are not counted as finished decisions.

After rollout, inspect oldest due age, arrivals, completions, processing time, actual
review outcomes and per-model usage. Restore a dedicated notification consumer only
if sustained delivery lag appears. Increase article replicas only if sustained arrivals or oldest-due age justify it. Make all capacity changes through GitOps.

The first live web-research call reported 21,958 tokens, exceeding the frozen-pilot
16,000-token per-call guard. Production therefore allows 40,000 per call while
retaining the 64,000-token whole-topic lifetime budget, five calls and four searches.
Already deferred runs retain their original charged budgets and remain pending for
explicit review; changing configuration does not silently replenish them.

## v0.0.11 correction

By 18:32 UTC the article queue had drained to zero with the same article consumer
and pooled capacity. Retain eight workers. Fourteen topic canaries were deferred
by discovery token guards, rather than rejected; automatic topic scheduling was
paused through GitOps while the correction was tested locally.

v0.0.11 skips discovery for usable source URL hints, restricts discovery to one
search without opening pages, and constrains evidence selectors. Live local tests
completed PostgreSQL with two Luna calls and 21,006 tokens; the corrected
ActionScript path took three calls and 53,785 tokens including discovery. These
focused tests do not establish broad quality equivalence. Resume with one active
review and inspect actual decisions before restoring admission to four. Recovery
for the exact failed canary cohort must use audited grants preserving prior costs.

At 19:01 UTC the v0.0.11 canary approved Adventure Game Interpreter in three Luna
calls (52,289 tokens) and Agent Browser in two (19,465 tokens, source hint without
search). Two ambiguous event identities remained pending after bounded correction.
All deployments were ready and Fleet had converged. Restore four active topic
decisions using the existing workers. A single audited recovery allowance targets
only the 14 previous guard failures; old spending remains charged.

The canary recovery completed through the normal database pooler at 19:07 UTC:
all 14 targeted cases received exactly one audited allowance and retained prior
charges. The successful post-upgrade Job cleaned itself up; its temporary manifest
was then removed. The migration-only direct database route was correctly blocked
for the recovery Job before it was corrected, with no partial grants.
