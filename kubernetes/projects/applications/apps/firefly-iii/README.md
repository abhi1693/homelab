# Firefly III

Firefly III runs as an internal Applications project app in the `finance`
namespace.

## Status

Firefly III runs with one web replica, an active daily `firefly-iii-cron`
CronJob, and one dedicated `firefly-iii-rw` PostgreSQL pooler instance. The
`finance` ApplicationProfile observes the web and importer workloads with
single-replica bounds and normal resource metrics.

## Access

- Internal URL: `http://finance.home`
- Ingress class: `traefik`
- Service port: `8080`

## Storage

Firefly persists uploaded attachments under `/var/www/html/storage/upload` on
the `firefly-iii-upload-nfs` PVC. NFS CSI provisions its retained NAS directory
below `finance/firefly-iii-upload-nfs`; the claim advertises `256Mi` while the
NAS controls actual capacity.

Financial records are stored in the shared CloudNativePG PostgreSQL cluster via
the `postgresql-pooler-firefly-iii-rw` PgBouncer pooler. The database and role
are owned by the database project PostgreSQL bundle.

## Resources

The web workload requests `30m` CPU and `103Mi` memory, with no CPU limit and a
`256Mi` memory limit. The memory headroom accommodates Firefly's sequential
database integrity and running-balance maintenance commands; do not run
memory-intensive maintenance commands concurrently in the web container.

## Scheduled Tasks

The `firefly-iii-cron` CronJob calls Firefly's static cron endpoint daily at
03:00. The token is stored in the
`firefly-iii` SOPS-managed Secret and must match the app's `STATIC_CRON_TOKEN`
environment variable. Completed Job objects expire after one hour so a past
failure cannot leave the cluster-wide `KubeJobFailed` alert firing indefinitely.

## Network Policy

The namespace is default-deny. Traefik and the Home Assistant application pods
can reach the web port. Home Assistant can use `http://finance.home:80` through
Traefik; its Cilium egress rule permits only HTTP GET requests to this host's
`/api/v1/*` paths. It can also connect directly to
`http://firefly-iii.finance.svc.cluster.local:8080`; paired ingress and egress
rules allow TCP 8080 only between these workloads. Firefly API authentication
is still required. Firefly can reach DNS and its PostgreSQL pooler, and the app
can make public HTTP/HTTPS requests for optional external integrations.

Home Assistant 2026.9.1's Firefly client uses port 9000 if no port is specified;
enter the explicit `:80` in its integration setup even though browsers do not
need it for this HTTP hostname.
