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

The receiver accepts browser telemetry from the public app hostnames listed in
`values.yaml`. It writes logs to Loki and traces to Tempo.

## Sourcemaps

Sourcemap lookup is configured for portfolio, personal blog, Indexly,
ShipyardHQ, Wardn Hub, and GitRank frontend services. The collector fetches
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
