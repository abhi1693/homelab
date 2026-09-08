# Cloudflare Tunnel Network Policies

This companion Fleet bundle owns the controller and connector network policies,
the controller disruption budget, and the connector's Cilium egress exception
for Music Assistant. It depends on the Cloudflare controller chart bundle.

The chart owns both metrics Services and ServiceMonitors through
`serviceMonitor.create`. Keep their definitions out of this bundle so Fleet
does not alternate ownership or change their selectors. Prometheus reaches the
controller on TCP `9090` and each connector on TCP `44483`.

See the [controller README](../cloudflare-tunnel-ingress-controller/README.md)
for monitoring, availability, and transport settings.
