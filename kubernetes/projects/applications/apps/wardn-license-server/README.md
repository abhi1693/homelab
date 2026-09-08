---
title: Wardn License Server
---

# Wardn License Server

Fleet deployment for the private `abhi1693/wardn-license-server` issuer and
administration console. The public route is
`https://licenses.wardnai.dev`; `/v1` and `/health` route to the FastAPI service
while the remaining paths route to the Next.js console.

The deployment uses the retained `wardn_license` database through a dedicated
two-replica PgBouncer pool. A pre-upgrade hook applies Alembic migrations
against the direct PostgreSQL writer before the API rolls out. API and frontend
both run two ARM64 replicas with disruption budgets and pod anti-affinity.
The console exposes stored activation keys only through an explicit authenticated
administrator reveal action; normal inventory and detail responses omit key material.

Dodo is deliberately configured for Test Mode. Product and add-on mappings are
server-owned in the `wardn-license-server-prerequisites` ConfigMap; credentials,
the webhook signing secret, license signing key, database URL, session secret,
and activation-key encryption secret are stored only in its SOPS Secret. Runtime
network policies live in the same prerequisite bundle, ensuring the migration
hook can read configuration and reach PostgreSQL before workloads are applied.
The public webhook URL is
`https://licenses.wardnai.dev/v1/webhooks/dodo`.

After rotating application secrets or changing runtime configuration, bump the
matching revision annotation in `deployment.yaml` so the pods consume the new
values.

Before the admin login can complete, add
`https://licenses.wardnai.dev/api/auth/oidc/callback` to the existing Zitadel Web
application's redirect URIs. Before switching Dodo to Live Mode, replace the
Test Mode business, product, add-on and API settings together, rotate the Dodo
webhook secret, and obtain Dodo's current delivery CIDRs. Until then, the
application accepts the Cloudflare connector pod CIDR as defense in depth and
still requires a valid Standard Webhooks signature on every event.
