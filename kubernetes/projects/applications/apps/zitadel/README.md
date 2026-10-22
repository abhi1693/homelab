# ZITADEL

ZITADEL is the central identity provider for cluster applications.

- External issuer: `https://auth.abhimanyu-saharan.com`
- Ingress class: `cloudflare-tunnel`
- Database: shared CNPG PostgreSQL through `postgresql-pooler-zitadel-rw`
- Secrets: SOPS-managed `zitadel-masterkey`, `zitadel-env`, `zitadel-login-env`, and `zitadel-postgresql`
- Core: upstream v4.19.4, pinned by image digest
- Chart: official `ghcr.io/zitadel/zitadel-charts/zitadel` OCI artifact, version 10.3.0

The chart's `wait-for-zitadel` init container is bounded through
`tools.wait4x.resources` at `10m`/`32Mi` requests and `100m`/`64Mi` limits.
Setup and cleanup jobs use the ARM64 `alpine/k8s:1.35.6` image through the local
registry cache. The Alpine shell is required by the chart's helper commands; review client
compatibility when the cluster or helper image changes.
Each ZITADEL server requests `40m` CPU and each Login UI replica requests
`40m`; the combined `160m` reservation stays well above the observed 7-day
aggregate p99 while both workloads remain CPU-burstable.

Each of the two ZITADEL servers is capped at eight open and four idle database
connections. The resulting 16-connection app budget fits within either
PgBouncer replica's backend limit, avoiding queueing when service load
balancing is uneven; the aggregate backend and PostgreSQL role limit are 32.

The Login UI uses a startup probe and less aggressive readiness/liveness
cadence than the chart defaults so pod replacements do not immediately produce
probe failure noise while the Next.js service starts.

## App Integration Contract

Applications should integrate with ZITADEL as separate OIDC or SAML clients in
ZITADEL. Do not share one OAuth client secret across apps. Each application gets
its own redirect URIs, allowed grant types, scopes, and token settings.

Use the issuer URL:

```text
https://auth.abhimanyu-saharan.com
```

OIDC discovery is expected at:

```text
https://auth.abhimanyu-saharan.com/.well-known/openid-configuration
```

The initial admin human username is `admin` with email
`admin@abhimanyu-saharan.com`; the bootstrap password is stored only in the
SOPS-managed `zitadel-env` secret and must be changed at first login.

The ZITADEL master key is intentionally stored in `zitadel-masterkey`. Losing
that key makes encrypted ZITADEL data unrecoverable.

The Login UI runs the digest-pinned `home-lab-zitadel-login:4.19.4-idp-retry1`
image. It retries only session lookup after successful GitHub account creation
and linking, covering transient user projection delay. See
[the image source](../../../../images/zitadel-login/README.md) for regression
tests, dependency pins, and rollback. The core server remains upstream v4.19.4.

## Upgrade operations

Fleet runs the chart init/setup hooks before replacing the server and Login UI.
The v4.15.3 to v4.19.4 upgrade includes database migrations; verify a successful
CNPG backup and continuous archiving before rollout. A core downgrade requires
a separate database compatibility review rather than just reverting image tags.

Login UI replicas share `ZITADEL_SESSION_COOKIE_SECRET` through
`login.sessionCookieSecretName: zitadel-login-env`. The SOPS-managed value must
be at least 32 characters. All replicas must use the same secret; comma-separated
keys support rotation. Existing unsigned Login UI cookies are rejected after
upgrade, requiring a fresh sign-in; application sessions and issued tokens remain
valid. Keep this secret separate from the core environment and app OIDC secrets.

After rollout, check successful init/setup jobs, Fleet desired/applied deployment
IDs, two ready replicas of both workloads, and the public OIDC discovery and
Login UI readiness endpoints. Verify app callbacks and fresh GitHub registration
before retiring the custom registration retry. See the
[upstream cookie-signing upgrade notes](https://github.com/zitadel/zitadel/releases/tag/v4.19.2).

## DevFeed virtual instance

DevFeed uses a separate virtual instance at `https://auth.devfeed.tech`, sharing
only the ZITADEL backend and PostgreSQL infrastructure. Its organizations,
users, clients, branding and SMTP configuration are independent of the home-lab
instance. DevFeed reader, admin and partner clients use this issuer after the
2026-10-20 [identity migration](../../../../../docs/runbooks/devfeed-identity-migration.md),
which retained existing application account UUIDs and social-login links.

The initial temporary System API identity was removed after provisioning.
Ongoing automation uses an account scoped only to DevFeed. The initial
administrator password is SOPS encrypted in `devfeed-secrets.sops.yaml`, under
`name: zitadel-devfeed-admin` and `stringData.admin-password`.

The desired generic SMTP provider is `smtp.mx.cloudflare.net:465` with TLS,
username `api_token`, sender `noreply@devfeed.tech` and display name `DevFeed`.
The password starts empty; no provider is activated until the operator supplies
its token through the encrypted GitOps secret. Never paste the token into chat.

DevFeed has two dedicated Login V2 replicas with an instance-scoped
`IAM_LOGIN_CLIENT` service account and separate signed-cookie secret. The
`devfeed-gitops` service account has `IAM_OWNER` only in the DevFeed instance;
its PAT is used by the five-minute `zitadel-devfeed-smtp` CronJob. Both PATs
expire on 2027-10-20 and must be rotated before that date.

SMTP settings live in `devfeed-instance.json`. The reconciler checks the exact
DevFeed instance ID before making changes, creates or updates only its managed
provider, and waits successfully while the SMTP password is empty. It allows
outbound TCP 465 from ZITADEL server pods. Once populated, the provider uses
implicit TLS, plain SMTP authentication over that TLS connection, and the
configured Cloudflare API token as its password. UI changes to this managed
provider are reconciled back to Git every five minutes.

To populate the token, run from the repository root:

```sh
sops kubernetes/projects/applications/apps/zitadel/devfeed-secrets.sops.yaml
```

Set `spec.secretTemplates` -> `name: zitadel-devfeed-smtp` ->
`stringData.password` to the token, save the encrypted file, then commit and
push. Fleet and the SOPS operator deliver the token to the CronJob; no manual
Kubernetes Secret changes are needed. Until then, SMTP delivery is pending.
Use the same encrypted file for initial administrator credentials; the username
is `admin` and the password must be changed on first login. Login V2 is enabled at
`https://auth.devfeed.tech/ui/v2/login`; open
`https://auth.devfeed.tech/ui/console` to manage the instance.

Validate the app with `kubectl kustomize`, render the pinned Helm chart with
`values.yaml`, run pre-commit, and use server-side dry runs for
`devfeed-login.yaml` and `devfeed-smtp.yaml`. After Fleet convergence, verify
both original workloads and both DevFeed login replicas, discovery issuers,
Login V2 readiness and the SMTP CronJob's pending/success status.
