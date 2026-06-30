# GitRank

Fleet-managed GitRank deployment for the home cluster.

Public traffic is exposed through the Cloudflare tunnel ingress controller.
`git-rank.dev` serves only the Next.js frontend. Public API, webhook, and
generated profile media traffic uses `api.git-rank.dev`.

PostgreSQL is provided by the shared Database project CNPG cluster through the
`postgresql-pooler-git-rank-rw` write pooler. Queue traffic uses the shared
Database project Valkey Sentinel service on logical DB index 30.

Required out-of-band secrets:

The image pull credential is the namespace-scoped `harbor-registry`
dockerconfigjson Secret for `registry.home`, backed by
`robot-namespace-git-rank`.

```bash
kubectl create namespace git-rank --dry-run=client -o yaml | kubectl apply -f -

kubectl -n git-rank create secret generic git-rank-runtime \
  --from-literal=CLERK_SECRET_KEY='<clerk-secret-key>' \
  --from-literal=GITHUB_APP_PRIVATE_KEY='<github-app-private-key>' \
  --from-literal=IDENTITY_WEBHOOK_SECRET='<identity-webhook-secret>' \
  --from-literal=GITHUB_WEBHOOK_SECRET='<github-webhook-secret>'

kubectl -n git-rank create secret generic postgresql-app \
  --from-literal=username='gitrank' \
  --from-literal=password='<shared-postgresql-password>' \
  --from-literal=dbname='gitrank'
```

The `git-rank-runtime` and `postgresql-app` secrets are manually managed. Do
not commit them.
