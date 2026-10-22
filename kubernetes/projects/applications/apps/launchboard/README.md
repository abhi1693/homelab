---
title: Launchboard
---

# Launchboard

Fleet deployment for the standalone
[`abhi1693/launchboard.win`](https://github.com/abhi1693/launchboard.win)
Next.js application.

## Shutdown state

Launchboard is paused through Fleet: the web Deployment has zero replicas,
the X automation CronJob is suspended, and the dedicated
`postgresql-pooler-launchboard-rw` pooler has zero instances. The Deployment's
migration init container cannot run while there are no web pods. An already
started automation Job must finish before shutdown verification is complete;
suspending its CronJob only prevents future schedules.

The database, role, encrypted credentials, namespace, Services, Ingress and
network policies remain retained. The pooler's PDB is omitted while there are
no matching pods, avoiding recurring `NoPods` events. The public uptime probe
also omits Launchboard during the pause. Public application requests are
expected to fail while its Service has no endpoints; the `www` hostname may
still return its edge redirect to the apex hostname.

Resume through Git in this order:

1. Restore two `launchboard-rw` instances in the PostgreSQL chart values and its
   PDB with `minAvailable: 1` and selector
   `cnpg.io/poolerName: postgresql-pooler-launchboard-rw`. Wait for database Fleet
   readiness and both pooler pods.
2. Restore one web replica and catalog `desiredReplicas: 1`. Verify the init
   migration, web readiness, Service endpoints and the public application.
3. Unsuspend X automation and restore `https://launchboard.win/` in the shared
   public Probe. Keep `startingDeadlineSeconds: 600` to bound missed schedules
   after a pause; resumption may start a recently missed run.

After shutdown, verify zero active app/automation/pooler pods, no ready Service
endpoints, a suspended CronJob, the absent pooler PDB, retained database and role,
and matching Fleet desired/applied deployment IDs.

## Retained application configuration

Launchboard owns the retained `launchboard` PostgreSQL database and role. Web
traffic, when resumed, uses the two-replica `postgresql-pooler-launchboard-rw`
service with a four-connection application pool. An init container runs the idempotent
migration against the direct read-write service before the web container
starts. This keeps first installation ordered behind SOPS secret decryption.

Release `0.1.19` stores OG image snapshots and PNGs in PostgreSQL. Migration
`004_social_card_cache.sql` adds a ranking trigger that changes the current
image version only when the #1 listing changes; clicks and repeat bids from the
same leader preserve the image. Cached images survive pod replacements and use
immutable versioned URLs. The unversioned `/api/og` route uses ETag revalidation.
The preview displays the winning bid at takeover and omits click counts.
Rollback uses the prior `0.1.18` image pins; the additive cache tables and
triggers are compatible with that release and can remain in place.

The public routes are `https://launchboard.win` and
`https://www.launchboard.win` through the Cloudflare Tunnel IngressClass.
NetworkPolicies default-deny the namespace, allow only the
Cloudflare connector into port 3000, permit DNS and the dedicated PostgreSQL
paths, and restrict website/Dodo/X fetches to public IPv4 HTTP(S) destinations.
The connector's matching egress allow rule is owned by the
`cloudflare-tunnel-ingress-controller-networkpolicy` bundle.

The application webhook is
`https://launchboard.win/api/webhooks/dodo`.
Verified payment and refund events are also sent to the Launchboard GA4 stream
when the encrypted application secret contains `GOOGLE_ANALYTICS_API_SECRET`;
the application safely skips those server-side events while it is absent.

The web container requests 50m CPU, with its existing burst capacity retained.
The [September 19 resource review](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-09-19-cpu-sizing-review)
records the seven-day usage and rollout checks.
