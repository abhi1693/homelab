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
- Requests: 50m CPU and 384Mi memory across both Alloy pods, config reloaders, and source-map resolvers

The receiver accepts browser telemetry from the public app hostnames listed in
`values.yaml`. It writes logs to Loki and traces to Tempo.

The replicas are stateless receivers. Required
hostname anti-affinity and the PodDisruptionBudget keep one receiver available
during voluntary disruption.

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

DevFeed reader/admin use a same-origin server receiver with an encrypted server-only
key. CORS includes `https://devfeed.tech` and `https://admin.devfeed.home`; policies
admit only `devfeed-faro=true` frontend pods on 12347. DevFeed source maps are fetched
from their private telemetry Services on 9100 under `/sourcemaps/`, outside Next's
public static tree. Public source-map fallback remains disabled.

Loki writes explicitly retry HTTP 429 and transient server failures with 1s–1m
backoff and 20 retries. Monitor `loki_write_dropped_entries_total` alongside Loki
rejections; successful HTTP readiness alone does not prove complete delivery.

## Private Turbopack source maps

The Python resolver sidecar listens only on loopback `127.0.0.1:12348` and is
not exposed by a Service or ingress. Alloy locations for portfolio, personal
blog, ShipyardHQ, and Wardn Hub use it. It first tries the expected `.js.map`
path; on a 404 it reads the JavaScript bundle from the fixed internal app origin
and follows its relative `sourceMappingURL` to the existing private map route.
Turbopack can hash JavaScript and source maps differently, so appending `.map`
to the JavaScript name alone fails even when the correct map exists.

The resolver rejects unknown apps, traversal, redirects, external map URLs,
invalid map JSON, and responses above 8MiB. Four concurrent resolutions are
allowed. Alloy provides the map cache. DevFeed keeps its dedicated private
telemetry endpoints. Public source-map fallback stays disabled and the existing
network policy still limits egress to the named frontend services.

Run `python -m unittest discover -s kubernetes/projects/system/apps/alloy-faro -p 'test_*.py'`
to validate alias resolution and path boundaries. When editing the resolver,
update `controller.podAnnotations.home-lab.io/sourcemap-resolver-revision` so
Fleet rolls both pods with the new mounted script.

## Session replay compatibility

Grafana's documented Session Replay collector and viewer are part of Grafana
Cloud Frontend Observability. The current self-hosted Alloy/Loki/Grafana pipeline
has no replay backend or viewer to enable. Adding `ReplayInstrumentation` alone
would not supply those services. A separate replay backend or a Cloud integration
needs its own deployment decision, masking configuration, and at-most-14-day
recording retention. No replay recording is enabled by this bundle.

See [Grafana's replay architecture](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-applications/session-replay/how-it-works/).
