# Hyperlocal Kitchen

Fleet deployment of application commit
`168f2c82c842f2a368b35bd796c3f240c3b1170e`. Images are published with ARM64
support and pinned by digest. The production Zitadel callback is registered
alongside the existing local development callbacks.

## Shutdown state

The admin UI, member API, admin API, worker, and Redis are shut down with all
five Deployments at zero replicas. The dedicated CNPG pooler
`postgresql-pooler-hyperlocal-kitchen-rw` is retained at zero instances. Its
PodDisruptionBudget is omitted from the pooler PDB bundle while shut down, so
the disruption controller does not report `NoPods` for an inactive pooler.
The migration Job is suspended and
Fleet's `helm.waitForJobs` is disabled so a suspended migration cannot block
reconciliation or run on a fresh installation.

The `kitchen` database and role, encrypted credentials, namespace, Services,
Ingress, and Redis PVC remain retained. Both public hostnames have no running
backend while this shutdown state is desired in Git.

To resume through GitOps, restore one replica in each of the five Deployment
manifests and two Kitchen pooler instances in the PostgreSQL chart values.
Restore the dedicated pooler PDB with `minAvailable: 1` in
`kubernetes/projects/database/apps/postgresql-pooler-pdb/pdb.yaml`, selecting
`cnpg.io/poolerName: postgresql-pooler-hyperlocal-kitchen-rw`. Unsuspend the migration Job and restore
`helm.waitForJobs: true` in `fleet.yaml`. Validate and publish these changes
together, then verify the migration, schema gates, pooler, application readiness,
and public endpoints before treating the application as available.

## Endpoints and authentication

- Admin: `https://kitchen-admin-af01fda18c31ce91fd5401ca6fbe71ad.abhimanyu-saharan.com`
- Member API: `https://kitchen-api-af01fda18c31ce91fd5401ca6fbe71ad.abhimanyu-saharan.com`
- Zitadel issuer: `https://auth.abhimanyu-saharan.com`
- Organization: `393940982594275036`
- Admin client: `393941078174140124`
- Required project role: `superuser`
- Token authentication: `none` (public PKCE S256 client).

In the existing admin application's Zitadel Redirect Settings, add exactly:

```text
https://kitchen-admin-af01fda18c31ce91fd5401ca6fbe71ad.abhimanyu-saharan.com/api/v1/auth/callback
```

Keep the existing localhost redirect for development. The signing-in user needs
`superuser` granted in the configured organization and project. The deployment
uses production mode and secure cookies. Resident authentication remains
unconfigured because the local configuration has no resident client ID; register
a separate application before enabling it, with callback
`https://kitchen-api-af01fda18c31ce91fd5401ca6fbe71ad.abhimanyu-saharan.com/api/v1/auth/callback`.

Cloudflare Tunnel supplies public TLS and manages DNS from `ingress.yaml`.
Both hostname labels contain a randomly generated 128-bit suffix. Zitadel remains
the access-control boundary; the hostname is public DNS and certificate metadata.
The admin API has only a ClusterIP Service and is reached through the admin UI's
same-origin gateway. The member API has its own long hostname.

## Runtime and persistence

Normal active sizing is one pod each for the member API, admin API, admin UI,
worker, and Redis; all five are currently scaled to zero.
All images target ARM64. Python runs as UID 10001, Next.js as UID 1000, and Redis
as UID 999. Containers drop capabilities, disable service-account tokens, and
use read-only root filesystems with writable temporary directories.

The existing shared CNPG cluster owns a new retained `kitchen` database and
non-superuser `kitchen` role. It uses the same database password as the local
`.env`, encrypted for the home-lab SOPS recipient. No local database rows are
copied: this prepares a fresh database in the lab. When active, an isolated pair
of session poolers supplies 48 backend slots with a role limit of 52; the
poolers are currently scaled to zero. SQLAlchemy's default
maximum is 15 per process: three steady backend processes need at most 45;
rolling an API adds another temporary process, whose connections can queue at
the pooler. Migrations use the direct database Service.

Redis uses database 0, AOF persistence (`appendfsync everysec`), and a retained
1 GiB Longhorn PVC, matching the local session-store behavior. It is internal
and reachable only from the APIs and worker. Secrets and Harbor pull credentials
are in `secrets.sops.yaml`. Non-secret app settings match local `.env`, with
cluster database/Redis addresses, HTTPS origins, and secure cookies substituted.

When active, `migration-job.yaml` runs `alembic upgrade head` as an ordinary
versioned Job and Fleet waits for it. It is suspended during shutdown.
Each backend process also waits until the database's Alembic
heads match the image before it starts. The APIs use `/ready` and `/health`
probes. Redis uses `redis-cli ping`; Next.js uses TCP probes because the login
page itself depends on the admin API.

Default-deny policies allow DNS, the Cloudflare connector, the admin gateway,
the dedicated PostgreSQL poolers/direct migration route, app-local Redis, and
public HTTPS to Zitadel. The app bundle also owns a narrowly scoped egress policy
in the Cloudflare namespace so its default-deny connector can reach only this
app's admin UI on port 3000 and member API on port 8000. Namespace ownership and PSA audit/warn labels follow
`docs/runbooks/fleet-namespace-psa-labels.md`.

## Publish and reconcile

1. Authenticate Docker to GHCR with permission to publish the two app packages.
2. Publish the exact committed source (the script archives tracked Git files,
   so local `.env` files are excluded):

   ```sh
   kubernetes/projects/applications/apps/hyperlocal-kitchen/publish-images.sh \
     /home/asaharan/PycharmProjects/hyperlocal-kitchen
   ```

3. Ensure Harbor's GHCR proxy has read access to both packages (public packages
   or configured upstream credentials). Check both manifest lists contain ARM64.
   Record the registry digests and append `@sha256:...` to the image references
   in all Deployments, the migration Job, and backend schema-wait init containers
   before delivery. The source tags are `sha-168f2c82c842f2a368b35bd796c3f240c3b1170e` and no `latest` tag is used.
4. Register the admin callback above in Zitadel.
5. Commit and push the app bundle, PostgreSQL prerequisites/values/dependencies,
   pooler PDB, workload catalog exclusion, GitRepo paths, and documentation.
   Fleet reconciles them; no manual cluster apply is part of this deployment.
6. Verify the database prerequisite bundle, PostgreSQL HelmOp, migration Job,
   app bundle, pod readiness, tunnel/DNS, and a real admin login.

For a subsequent app revision, update all backend/frontend image references,
change the migration Job name to a new revision suffix, and update
`publish-images.sh`'s source commit. Bump the pod-template config checksum when
changing ConfigMap contents and bump a pod annotation after secret changes.
The old completed migration Job is replaced declaratively; don't remove
Alembic history or reset the database.

## Validation

```sh
python scripts/check-kubernetes-resource-bounds.py \
  kubernetes/projects/applications/apps/hyperlocal-kitchen
python scripts/validate-workload-catalog.py
bash -n kubernetes/projects/applications/apps/hyperlocal-kitchen/publish-images.sh
helm template postgresql cluster --repo https://cloudnative-pg.github.io/charts \
  --version 0.9.0 -f kubernetes/projects/database/apps/postgresql/values.yaml
```

Once the cluster API is reachable, use read-only checks:

```sh
kubectl -n fleet-local get gitrepo home-lab-applications home-lab-database
kubectl -n fleet-local get bundles | rg 'hyperlocal-kitchen|postgresql'
kubectl -n hyperlocal-kitchen get jobs,pods,deployments,pvc,ingress
kubectl -n postgresql get pooler postgresql-pooler-hyperlocal-kitchen-rw
kubectl -n hyperlocal-kitchen get endpointslices
```

For the current shutdown, require zero desired/running Deployment and pooler
replicas, no active migration pods, the suspended Job, no ready Service
endpoints, and the original Redis PVC still bound. After resuming, check the
migration logs and both public health/authentication endpoints as well.

Server-side dry runs require the target namespaces and CRDs to exist. First
validate `namespace.yaml`, then validate rendered built-in resources and the
SOPS/NetworkPolicy resources as their namespaces become available. A local
validation pass does not establish a successful live rollout.
