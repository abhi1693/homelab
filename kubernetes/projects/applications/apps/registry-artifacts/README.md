# Registry Artifacts

`registry-artifacts` is the continuous controller for local Harbor artifacts.
It replaces the old `harbor-cache-warmer` and Harbor replication reconciliation
CronJobs.

The unauthenticated management UI is exposed only on local Traefik ingress at
`http://registry-artifacts.home`.

Required out-of-band secrets:

```bash
kubectl -n postgresql create secret generic registry-artifacts-postgresql-app \
  --type=kubernetes.io/basic-auth \
  --from-literal=username=registry_artifacts \
  --from-literal=password='<generated-password>' \
  --from-literal=dbname=registry_artifacts

kubectl -n registry-artifacts create secret generic registry-artifacts-postgresql-app \
  --from-literal=username=registry_artifacts \
  --from-literal=password='<same-generated-password>' \
  --from-literal=dbname=registry_artifacts

kubectl -n registry-artifacts create secret generic registry-artifacts-runtime \
  --from-literal=HARBOR_USERNAME=admin \
  --from-literal=HARBOR_ADMIN_PASSWORD='<harbor-admin-password>' \
  --from-literal=LOCAL_REGISTRY_USERNAME=admin \
  --from-literal=LOCAL_REGISTRY_PASSWORD='<harbor-admin-password>' \
  --from-literal=GHCR_USERNAME='<github-username>' \
  --from-literal=GHCR_PASSWORD='<github-token-with-package-read>'
```

Do not commit these credentials.

Non-secret controller defaults such as Harbor URL, logging, database pool
limits, request timeouts, and default upstream registry settings are tracked in
the `registry-artifacts` ConfigMap.
