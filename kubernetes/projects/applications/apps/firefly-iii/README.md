# Firefly III

Firefly III runs as an internal Applications project app in the `finance`
namespace.

## Access

- Internal URL: `http://finance.home`
- Ingress class: `traefik`
- Service port: `8080`

## Storage

Firefly persists uploaded attachments under `/var/www/html/storage/upload` on
the `firefly-iii-upload` Longhorn PVC. The claim starts at `256Mi`.

Financial records are stored in the shared CloudNativePG PostgreSQL cluster via
the `postgresql-pooler-firefly-iii-rw` PgBouncer pooler. The database and role
are owned by the database project PostgreSQL bundle.

## Scheduled Tasks

The `firefly-iii-cron` CronJob calls Firefly's static cron endpoint daily at
03:00. The token is stored in the `firefly-iii` SOPS-managed Secret and must
match the app's `STATIC_CRON_TOKEN` environment variable.

## Network Policy

The namespace is default-deny. Traefik can reach the web port, Firefly can reach
DNS and its PostgreSQL pooler, and the app can make public HTTP/HTTPS requests
for optional external integrations.
