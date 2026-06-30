# ADR-001: Redesign Jellyfin For Horizontal Scaling

## Status

Proposed

## Context

The current Jellyfin deployment is a single process with SQLite-backed state on
Longhorn RWO volumes and media on the NAS-backed `media-library-nas` PVC. This
can fail over, but it cannot horizontally scale without sharing mutable local
state between pods.

The target is active-active Jellyfin replicas for more concurrent streaming and
better node-failure behavior. Running multiple pods against the same SQLite
files is rejected because it keeps the core write bottleneck and risks database
locking or corruption.

## Decision

Build a repo-owned ARM64 Jellyfin image with the current live Jellyfin plugin
set and the experimental PostgreSQL provider, then make the shared CloudNativePG
cluster the canonical relational state store for Jellyfin.

The image will also carry a small Jellyfin core patch that makes device session
and access-token reads use PostgreSQL as the source of truth. Without that
patch, each pod only trusts the in-memory `DeviceManager` cache populated at
startup, so browser logins created on one pod fail with `Invalid token` when
requests reach another pod.

Jellyfin will use:

- A dedicated PostgreSQL role and database named `jellyfin`.
- The app-specific PgBouncer service
  `postgresql-pooler-jellyfin-rw.postgresql.svc.cluster.local`.
- The repo-owned image tag family `ghcr.io/abhi1693/home-lab:jellyfin*`.
- Jellyfin plugin assemblies pinned in the image so every replica loads the
  same plugin versions.
- A patched `Jellyfin.Server.Implementations.dll` for database-backed device
  token lookup.
- Plugin configuration and credentials mounted as ConfigMaps and Secrets rather
  than baked into the image.

The live Jellyfin release remains on the current single-instance deployment
until migration, secrets, and non-relational state handling are complete.

## Target Architecture

The full horizontal design has five state boundaries:

1. **Relational state**: PostgreSQL through the Jellyfin PostgreSQL provider.
2. **Mutable configuration**: move remaining XML/config state into generated
   ConfigMaps, Secrets, immutable config layers, or database-backed
   configuration.
3. **Metadata and generated assets**: store actor images, artwork, trickplay,
   and generated metadata in a shared content-addressed store or RWX/object
   backend that every replica can read.
4. **Singleton work**: guard migrations, scheduled tasks, library scans, and
   metadata writes with a PostgreSQL advisory lock or Kubernetes Lease so only
   one replica performs cluster-wide mutation at a time.
5. **Playback/transcode state**: make stream sessions resumable across replicas
   by externalizing segment/session ownership, or by serving transcode segments
   from a shared segment store. Sticky sessions alone are not the target end
   state.

## Rationale

PostgreSQL removes the most important shared SQLite limitation and matches the
repo's existing shared database contract. It also gives the future fork a place
to implement distributed locks, migration fencing, and notification fan-out
without adding another coordination system first.

The repo-owned image is required because the public PostgreSQL-provider image
does not currently publish an ARM64 manifest, while this cluster schedules media
apps on ARM64 Raspberry Pi nodes.

## Trade-offs

- The upstream PostgreSQL provider is experimental, so this starts as a lab
  cutover rather than a blind production replacement.
- PostgreSQL does not solve every state boundary. Metadata files, XML config,
  scheduled jobs, websocket/session notifications, and transcode segments still
  need hardening before the system is truly active-active.
- Keeping the image in this repo increases maintenance work whenever Jellyfin,
  a plugin, or the PostgreSQL provider changes.

## Consequences

- Positive: Jellyfin can be moved toward real shared-state replicas instead of
  cloned independent servers.
- Positive: database access follows the existing CNPG/PgBouncer/NetworkPolicy
  model used by other apps.
- Negative: the first cutover must be treated as a migration project with
  rollback.
- Mitigation: keep current Jellyfin manifests unchanged until the image is
  published, secrets exist, and a copy of the current SQLite data has been
  migrated and tested.

## Revisit Trigger

Revisit this ADR when Jellyfin ships native supported PostgreSQL or when the
custom image has replaced the remaining filesystem-local state with shared
providers.
