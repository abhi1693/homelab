---
title: Launchboard
---

# Launchboard

Fleet deployment for the standalone
[`abhi1693/launchboard.win`](https://github.com/abhi1693/launchboard.win)
Next.js application.

Launchboard owns the retained `launchboard` PostgreSQL database and role. Web
traffic uses the two-replica `postgresql-pooler-launchboard-rw` service with a
four-connection application pool. An init container runs the idempotent
migration against the direct read-write service before the web container
starts. This keeps first installation ordered behind SOPS secret decryption.

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
