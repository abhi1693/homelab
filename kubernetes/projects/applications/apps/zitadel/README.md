# ZITADEL

ZITADEL is the central identity provider for cluster applications.

- External issuer: `https://auth.abhimanyu-saharan.com`
- Ingress class: `cloudflare-tunnel`
- Database: shared CNPG PostgreSQL through `postgresql-pooler-zitadel-rw`
- Secrets: SOPS-managed `zitadel-masterkey`, `zitadel-env`, and `zitadel-postgresql`
- Chart: official `ghcr.io/zitadel/zitadel-charts/zitadel` OCI artifact

The chart's `wait-for-zitadel` init container is bounded through
`tools.wait4x.resources` at `10m`/`32Mi` requests and `100m`/`64Mi` limits.
Each ZITADEL server requests `25m` CPU and each Login UI replica requests
`15m`; the combined `80m` reservation stays well above the observed 7-day
aggregate p99 while both workloads remain CPU-burstable.

Each of the two ZITADEL servers is capped at eight open and four idle database
connections. The resulting 16-connection app budget fits within either
PgBouncer replica's backend limit, avoiding queueing when service load
balancing is uneven; the aggregate backend and PostgreSQL role limit are 32.

The Login UI uses a startup probe and less aggressive readiness/liveness
cadence than the chart defaults so pod replacements do not immediately produce
probe failure noise while the Next.js service starts.

## App Integration Contract

Applications should integrate with ZITADEL as separate OIDC or SAML clients in
ZITADEL. Do not share one OAuth client secret across apps. Each application gets
its own redirect URIs, allowed grant types, scopes, and token settings.

Use the issuer URL:

```text
https://auth.abhimanyu-saharan.com
```

OIDC discovery is expected at:

```text
https://auth.abhimanyu-saharan.com/.well-known/openid-configuration
```

The initial admin human username is `admin` with email
`admin@abhimanyu-saharan.com`; the bootstrap password is stored only in the
SOPS-managed `zitadel-env` secret and must be changed at first login.

The ZITADEL master key is intentionally stored in `zitadel-masterkey`. Losing
that key makes encrypted ZITADEL data unrecoverable.
