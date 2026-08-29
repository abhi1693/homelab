# Alloy Faro

This bundle runs the public frontend telemetry collector for browser RUM data.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `alloy`
- Release: `alloy-faro`
- Ingress class: `cloudflare-tunnel`
- Public host: `rum.abhimanyu-saharan.com`
- Faro receiver port: `12347`
- Metrics port: `12345`
- Secret: `alloy-faro` supplies the Faro API key
- Replicas: 2, with required hostname anti-affinity across control-plane nodes
- Disruption budget: `minAvailable: 1`
- Requests: 30m CPU and 320Mi memory across both Alloy pods and config reloaders

The receiver accepts browser telemetry from the public app hostnames listed in
`values.yaml`. It writes logs to Loki and traces to Tempo.

Each pod's requests retain headroom over the 14-day pod p95 of approximately
5.2m CPU and 106Mi memory. The replicas are stateless receivers. Required
hostname anti-affinity and the PodDisruptionBudget keep one receiver available
during voluntary disruption, including descheduler balancing.

## Sourcemaps

Sourcemap lookup is configured for portfolio, personal blog, ShipyardHQ, and
Wardn Hub frontend services. The collector fetches
sourcemaps from internal service URLs rather than downloading them from public
origins.

## Network Boundary

Ingress is limited to the Cloudflare tunnel connector on port `12347` and
Prometheus on port `12345`. Egress is limited to DNS, Loki, Tempo, and the
specific frontend services used for sourcemaps.

## Operating Notes

- Add new public apps to both `cors_allowed_origins` and the NetworkPolicy when
  they send Faro telemetry.
- Keep the API key in SOPS, not plaintext.
- Review sourcemap paths whenever a frontend framework or asset prefix changes.
- Keep at least two eligible control-plane nodes while the two-replica
  anti-affinity rule is enabled.
