---
title: Indexly
---

# Indexly

Fleet-managed deployment for the `abhi1693/indexly` Next.js application.

## Runtime Dependencies

- `indexly` ConfigMap for Git-tracked non-secret production environment
  variables.
- `indexly-runtime` Kubernetes secret with only secret production environment
  variables copied from Vercel.
- Namespace-scoped `harbor-registry` image pull Secret for `registry.home`,
  backed by `robot-namespace-indexly`.
- Cloudflare Tunnel ingress for `indexly.cc`.

## Cron Replacement

Vercel cron jobs are represented as Kubernetes CronJobs:

- `indexly-poll-sitemaps`: `*/15 * * * *`
- `indexly-sync-subscriptions`: `0 * * * *`
