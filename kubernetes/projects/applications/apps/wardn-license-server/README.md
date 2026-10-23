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
Image automation follows the published backend/frontend Docker packages in one
reviewed Renovate group, including the migration-hook reference. GitHub release
metadata starts image publication and is not proof that both final images exist.
Before updating the three references, verify the exact source/version, successful
native release scans/SBOMs/runtime checks, ARM64 manifests and immutable Harbor
digest equality. The private source workflow disables unsupported GitHub artifact
attestations; this is not a signed-provenance claim. Other dependency updates
retain their normal automerge policy. The metadata change alone keeps existing
image values and workloads unchanged.
The release update also enables `check_license_image_cohort` in
`scripts/check-renovate-policy.py`: all three reviewed containers must select
one stable application version, with immutable SHA-256 pins and the same backend
digest in the API and migration hook. Frontend has its own verified digest.
Partial tag/digest updates, swapped container images, omitted migration hooks
and unreviewed extra references fail validation. There is no legacy unpinned
image exception. Registry availability and release checks remain separate gates.
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

## Runtime release 0.1.2

The API, console and direct-writer Alembic hook use verified immutable 0.1.2
images. The API runs Python 3.12.15 and reports matching installed/API version
metadata; the console runs Node 26.12.1 and Next 16.4.2. Native release checks
cover both architectures, strict scans, SBOMs, real HTTP/assets and cryptographic
bindings. Existing migration files are unchanged at head `202609040002`; Fleet
waits for the normal migration hook before replacing the two API and two console
replicas. Runtime installers are removed, and the console keeps its existing
restricted egress policy.
