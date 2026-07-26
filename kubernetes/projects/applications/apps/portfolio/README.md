---
title: Portfolio
---

# Portfolio

Fleet-managed deployment for the `abhi1693/portfolio` standalone Next.js
application.

The custom Deployment retains two ReplicaSet revisions; Git and Fleet history
remain the primary rollback path.

## Runtime Dependencies

- Namespace-scoped `harbor-registry` image pull Secret for `registry.home`,
  backed by `robot-namespace-portfolio`.
- Cloudflare Tunnel ingress for `abhimanyu-saharan.com` and
  `www.abhimanyu-saharan.com`.
