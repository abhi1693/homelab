# DevFeed PostgreSQL prerequisites

Provides SOPS-managed credentials for the retained `devfeed` and
`devfeed_chimely` roles/databases managed by the shared PostgreSQL chart. Allows
DevFeed database clients to reach only their session pooler, and permits the
release migration Job to reach the direct writer service. The pooler's API-server
and DNS access follow the existing CloudNativePG bootstrap policy.

The PostgreSQL HelmOp depends on this bundle so passwords exist before role
reconciliation. The application bundle depends on PostgreSQL and these policies.

The migration policy allows the retained `devfeed-migrate-v0005` bootstrap Job and
`devfeed-migrate-v0006` predecessor, plus `devfeed-migrate-v0007`, which upgrades
DevFeed through schema `0005` using the direct writer URL. Other application clients continue to use the session pooler.

The narrowly allowed `devfeed-migrate` Helm pre-upgrade hook connects to the
direct database writer. It runs the current release image and must succeed before
Helm replaces application workloads. Obsolete release-specific Job names have
been removed from the allowlist. Application traffic continues through its
separate pooler policy.
