---
title: Wardn AI Website
---

# Wardn AI Website

Fleet-managed deployment for the public Wardn AI product website at
`https://wardnai.dev`.

The website follows the existing Wardn frontend deployment contract: a
Next.js standalone server on port `3000`, one Linux/ARM64 replica, the
`registry.home` GHCR pull-through cache, and the namespace-scoped
`harbor-registry` image pull Secret.

The bundle uses the shared `wardn` namespace and depends on `wardn-hub`, which
owns that namespace, the registry Secret, and the namespace-wide default-deny
NetworkPolicy. Its app-local NetworkPolicy allows only the controlled
Cloudflare connector to reach the website service.

Git and Fleet history are the primary rollback path; the Deployment retains
two ReplicaSet revisions.

The website requests `10m` CPU without a CPU limit. Recheck this small
reservation against sustained public traffic before treating it as a stable
capacity baseline.
