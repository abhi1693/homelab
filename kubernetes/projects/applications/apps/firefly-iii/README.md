# Firefly III

Firefly III runs as an internal Applications project app in the `finance`
namespace.

## Status

Firefly III normally runs with one web replica, an active daily
`firefly-iii-cron` CronJob, and one dedicated `firefly-iii-rw` PostgreSQL
pooler instance. The
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

The in-cluster `firefly-monthly-start` and `firefly-monthly-stop` CronJobs
manage the monthly quiet period without GitHub Actions: they start the pooler
and web Deployment on the 1st at 02:15 Asia/Kolkata, then suspend the daily
maintenance CronJob and scale down the web Deployment and dedicated pooler on
the 6th at 06:17 Asia/Kolkata. The start job waits for the pooler and web
Deployment to become available before resuming daily maintenance. The shared
PostgreSQL cluster remains running. Fleet ignores only the runtime-controlled
replica and suspend fields when checking drift. The web Deployment omits
`spec.replicas`, and daily CronJob omits `spec.suspend`, so subsequent Helm
upgrades preserve the monthly scaler's runtime state. Kubernetes defaults a
new installation to one replica and an unsuspended daily CronJob. Removing
previously declared fields can reset them once during an ownership transition;
verify and restore the scheduled state after that upgrade.

The scaler's named-resource RBAC permits `get` before patching the daily
CronJob or dedicated pooler, and name-filtered `list`/`watch` for Deployment
waits and rollout checks. These reads are required by `kubectl` even when the
command targets a single resource.

The missed 6 October 2026 shutdown was restored with a temporary Fleet-managed
Job after repairing RBAC and Helm field ownership. Recovery verified that web
and pooler replicas were zero and daily maintenance was suspended before
removing the original failed Job. The temporary recovery Job and its narrowly
scoped cleanup permission were removed through Git after verification.

Recover future missed lifecycle runs with an ordinary Fleet-managed Job using
a unique name, a guarded schedule window, and explicit checks of workload
state before cleanup. Verify successful completion separately from Fleet
readiness, then remove the temporary Job through Git. Its pod template is
immutable, so a changed template requires a new Job name.

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
