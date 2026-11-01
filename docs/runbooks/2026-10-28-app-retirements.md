# Application retirements — 28 October 2026

The operator retired Hyperlocal Kitchen, Launchboard, NetBox MCP Server,
Wardn License Server, Wardn AI and Wardn AI Website.

Runtime controllers, scheduled automation and public/internal service endpoints
are removed through their existing Fleet owners. Hyperlocal Kitchen,
Launchboard, Wardn AI and Wardn License Server were already paused; the active
runtime savings come from NetBox MCP Server and Wardn AI Website. The four
paused PostgreSQL pooler definitions are removed as well.

Existing namespace, PVC and credential ownership remains in the original
retention-only bundles. Shared PostgreSQL databases and roles are retained.
NetBox, Wardn Hub, shared PostgreSQL and Valkey remain active. Retention bundles
have no application controllers, Jobs, CronJobs or ingress.

Episeerr is retained: the live log review showed reconciliation of 57 watch
events, scheduled cleanup and configured Sonarr/Jellyseerr webhooks. It owns the
season-delay workflow, so deleting it could strand delayed requests. The review
also found unresolved rule tags; repair them separately without removing the
season gate or triggering a bulk search.

Validate retirement using Fleet desired/applied deployment IDs, absence of the
six app families' Deployments and scheduled Jobs, and unchanged retained PVC
UIDs. PostgreSQL must remain 3/3 healthy. No namespace is deleted or relabeled.
