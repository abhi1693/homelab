# wardn-ai — retired

Retired on 2026-10-28 at the operator's request. Deployments, Jobs,
CronJobs, services, ingress, app configuration and runtime access were removed.
This existing Fleet bundle owns retained namespace/storage/credentials only;
it runs no application pods and exposes no application endpoint.

Shared PostgreSQL data and any existing app PVCs are retained. Dedicated pooler
definitions are removed. Restore runtime manifests from Git history only after
an explicit resumption request; do not silently reintroduce paused controllers.

See [the retirement record](../../../../../docs/runbooks/2026-10-28-app-retirements.md).
