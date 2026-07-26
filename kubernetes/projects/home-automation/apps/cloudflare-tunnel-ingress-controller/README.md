---
title: Cloudflare Tunnel Ingress Controller
---

# Cloudflare Tunnel Ingress Controller

Fleet installs the `strrl.dev/cloudflare-tunnel-ingress-controller` Helm chart into
the `cloudflare` namespace. Public applications opt in by setting
`spec.ingressClassName: cloudflare-tunnel` on their Kubernetes `Ingress`.

The controller uses the existing Cloudflare tunnel named `production-apps` and
manages DNS records plus tunnel ingress rules for matching Ingress objects.
Cloudflare API credentials are stored only in the SOPS-encrypted secrets bundle.
The chart reads the resulting Secret in the `cloudflare` namespace:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-tunnel-ingress-controller
  namespace: cloudflare
stringData:
  api-token: <cloudflare-api-token>
  cloudflare-account-id: <cloudflare-account-id>
  cloudflare-tunnel-name: production-apps
```

The token must allow `Account.Cloudflare Tunnel:Edit`, `Zone.DNS:Edit`, and
`Zone.Zone:Read`.

Images are pulled through the local Harbor proxy cache:

- `registry.home/cr.strrl.dev/strrl/cloudflare-tunnel-ingress-controller`
- `registry.home/docker.io/cloudflare/cloudflared`

These proxy-cache projects are public in Harbor, so the controller and
controller-managed `cloudflared` connector pods do not need an image pull
Secret.

The chart exposes connector metrics through the controller-managed
`cloudflared` pods on port `44483`. `cloudflaredServiceMonitor.create` is enabled
so Rancher Monitoring scrapes those metrics through the chart-owned Prometheus
Operator `ServiceMonitor`. The controller exposes controller-runtime metrics on
port `8080`; the companion raw Fleet bundle adds its metrics `Service` and
`ServiceMonitor`. The companion NetworkPolicies allow only the Rancher
Monitoring Prometheus pods to reach either metrics port.

The Rancher Monitoring bundle keeps the existing cloudflared Grafana dashboard
and adds alerts for lost connector scrape redundancy, fewer than four edge
connections per connector, readiness failures, connector configuration-version
drift, origin proxy errors, a sustained high 5xx rate, a missing controller
leader, and controller reconciliation failures.

Connector transport is pinned to HTTP/2 over TCP port `7844`. Both protocols
pass the `cloudflared` startup precheck, but the home network's QUIC path has
experienced repeated periods where all edge connections timed out. The
companion egress NetworkPolicy permits TCP `7844` for this fallback.

Both control-plane and data-plane workloads run with two replicas and required
pod anti-affinity on `kubernetes.io/hostname`, so Kubernetes cannot place both
replicas of either workload on the same node. A `PodDisruptionBudget` with
`minAvailable: 1` protects each workload during voluntary disruptions. The
chart owns the connector budget, while the companion
`cloudflare-tunnel-ingress-controller-networkpolicy` raw Fleet bundle owns the
controller budget because chart `0.0.24` does not expose a controller PDB
setting.

Each connector requests `40m` CPU and keeps CPU uncapped, preserving burst
capacity while avoiding reservation at the connector's short-lived peak.

The controller and its managed connector use restricted pod and container
security contexts: UID/GID `65532`, non-root execution, the runtime-default
seccomp profile, no privilege escalation, no Linux capabilities, and a
read-only root filesystem.

Only the connector readiness probe calls `http://localhost:44483/ready`.
Liveness and startup probes are intentionally omitted. The readiness endpoint
fails when `cloudflared` has no active edge connections, which should remove the
pod from ready endpoints but must not restart it. Using the same endpoint for
liveness or startup would cause avoidable restart loops during an ISP outage
and delay recovery when the WAN returns.

Chart `0.0.24` passes `cloudflared.resources` to the controller-generated
connector Deployment and grants the controller namespace-scoped access to its
managed `controlled-cloudflared-token` Secret. Keep the chart and controller
image versions aligned because the connector reconciliation contract spans
both.

Chart and controller `0.0.24` do not support a connector Deployment
`revisionHistoryLimit`. The controller's strict customization schema rejects
unknown fields, and each reconciliation replaces the managed Deployment spec,
so a separate patch would drift and be removed. A future controller release
should add an optional `revisionHistoryLimit` customization and render a low
value such as `2`. Until that upstream capability exists, connector tokens are
referenced from `controlled-cloudflared-token` rather than embedded in pod
commands, and obsolete pre-migration ReplicaSets must not be retained.

The companion `cloudflare-tunnel-ingress-controller-secrets` raw Fleet bundle
owns the namespace `LimitRange` as a fallback for workloads without explicit
resources; the connector's explicit requests and limits remain authoritative.

The companion network-policy bundle also grants the connector a Cilium
`remote-node` egress exception on TCP `8097` for Music Assistant's public Alexa
stream route. Music Assistant uses host networking, so Cilium assigns the
destination the `remote-node` identity; a standard pod selector or LAN
`ipBlock` does not match that path.
