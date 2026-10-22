# Slack alert notifications

The Fleet-managed `home-lab-slack` AlertmanagerConfig delivers non-Watchdog,
non-`none` severity alerts. Its webhook remains in the existing SOPS-managed
Secret. Routing and templates live in
[`alertmanager-slack.yaml`](../../kubernetes/projects/system/apps/rancher-monitoring/alertmanager-slack.yaml).
Do not post test messages or create production test alerts during routine
validation; the local validator uses a disposable HTTP capture receiver.

## Reading a notification

The title reports firing and resolved counts. Each detail identifies its own
status, severity, alert name, source and rejection reason when present. A FIRING
title can contain resolved members when another member is still firing. The
Notification field comes from Alertmanager's native notification reason: first
notification, new alerts added, some alerts resolved, all alerts resolved, or
repeat interval elapsed.

The message includes at most four detailed alerts, prioritizing firing permanent
loss. Longer groups state the total and link to Alertmanager. Individual details
link to a runbook, dashboard or query; text and link lengths are bounded. Open
the full group for all members and untruncated annotations. A mixed group's
severity field highlights any firing critical member even when its detail is
behind the overflow link. Missing namespace labels display "not provided"
rather than implying that the alert must be cluster-scoped.

Related telemetry alerts explicitly share `incident=log-delivery`,
`metric-delivery` or `trace-delivery`. They group by incident, cluster and
namespace, preserving each alert's severity and source. Fast and slow DevFeed
availability burns group by cluster, namespace, application and service. Other
alerts retain grouping by alert name, cluster, namespace and severity. These
groups correlate symptoms; they do not establish a common root cause.

No new inhibition rules hide downstream symptoms. Alloy permanent loss remains
visible alongside critical Loki WAL failures or rejections. Queue saturation,
final send failure and backend rejection counters describe different stages;
do not add them together or infer permanent loss from queue pressure alone.

## Why updates can arrive before four hours

The route keeps `groupWait: 30s`, `groupInterval: 5m` and `repeatInterval: 4h`.
The five-minute interval permits notifications when firing/resolved group
membership changes. Four hours applies to an unchanged group. Annotation count
changes alone do not create a new alert fingerprint. See the
[upstream routing semantics](https://prometheus.io/docs/alerting/latest/configuration/).

On 2026-10-19, the 03:30–06:34 UTC history showed four stable Alloy pod/reason
identities repeatedly firing for about 8.5 minutes and clearing for 2–4 minutes.
Their staggered transitions changed group membership. The previous Slack
template rendered firing and resolved members without distinguishing them, so
different updates could look identical. Two Prometheus replicas correctly
dropped the replica label, both Alertmanager peers stayed connected, one Slack
integration was configured, and the inspected eight-hour window showed no
notification failures or mesh failures. Delivery counters cannot identify
payloads, so identical-payload duplication was not proven. Private histories,
sanitized configurations and delivery-counter brackets are saved outside Git.

`AlloyLogEntriesDropped` now keeps firing for ten minutes after its last positive
evaluation, bridging those brief quiet gaps without adding an initial rule
pending period or raising its threshold. A new group still waits 30 seconds;
new members joining an existing group can wait until its next five-minute
update. Its annotation describes the last positive rolling
ten-minute window; that count can remain visible during the recovery hold.
Resolution means the detection and recovery windows cleared. Lost entries remain
lost. This reduces repeated closing/reopening; genuinely new sources or related
failures can still produce five-minute group updates.

Alertmanager provides at-least-once delivery. A real mesh partition can produce
duplicate notifications by design; a longer repeat interval cannot fix that.
See [upstream HA behavior](https://prometheus.io/docs/alerting/latest/high_availability/).

## Diagnosis and validation

For another noisy period, preserve exact Slack timestamps and alert identities.
Inspect both Prometheus replicas' alert state history and relabel configuration,
then both Alertmanagers' effective routes, group membership, peer health and
notification failure counters. Compare newly firing and resolved identities,
not just the displayed count. Distinguish a new group, changed membership,
four-hour repeat, delivery retry and fail-open duplicate before changing timers.
Do not print or save raw webhook URLs. Capture evidence privately outside Git.

```sh
python -m pip install --requirement .github/requirements/alertmanager.txt
python scripts/validate-alertmanager-notifications.py
python scripts/check-loki-observability.py
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/rancher-monitoring/alertmanager-slack.yaml
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/loki/prometheusrule.yaml
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/opentelemetry-collector/prometheusrule.yaml
```

The Docker validator uses Alertmanager/amtool 0.34.1 and synthetic local data.
Only its disposable timing copy accelerates intervals; Git's four-hour repeat
is checked separately. It checks routes, templates, mixed statuses, permanent
loss visibility, overflow and actual local notifier behavior. An optional
`--effective-config <private-sanitized-yaml>` checks the operator-compiled route,
receiver and existing inhibition behavior after Fleet reconciles. The validator
replaces the webhook before writing local configuration; it never contacts Slack.

Publish changes through Git and Fleet. Require Installed and Ready conditions,
matching desired/applied deployment IDs, successful Alertmanager reload on both
peers, healthy Prometheus rules and unchanged storage/pod identities. Observe
natural notification counters without injecting production incidents. A healthy
reload and local capture do not prove how Slack displayed a historical message.
Rollback means reverting the Git change, keeping the existing webhook Secret,
Alertmanager volumes and HA peers intact.

## Acceptance on 2026-10-19

Fleet reconciled change `401582859` with all 123 BundleDeployments Ready.
Both Prometheus replicas loaded the permanent-loss rule with a 600-second
recovery hold, zero initial pending period and healthy evaluation. Both
Alertmanager peers reloaded matching scoped routes/templates while retaining
their pod and storage identities. The
[ARM64 notification check](https://github.com/abhi1693/home-lab/actions/runs/39229975806)
and 18 Loki rule scenarios passed. The operator-compiled configuration also
passed the local notifier test with all four existing inhibition rules retained,
including final-send and Hubble-loss visibility beside critical alerts. No
synthetic production alert was injected; local captures validate the payload
and timing contract rather than the Slack client's visual presentation.
