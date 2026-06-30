# Personal Blog

Fleet-managed deployment for the personal blog.

The public hostname is `blog.abhimanyu-saharan.com`.

The app-owned Cloudflare Tunnel ingress and service are both named
`personal-blog` in the `personal-blog` namespace. Cloudflare serves public HTTPS,
the tunnel transport is encrypted, and the final in-cluster hop to the app pods
uses HTTP:

```text
http://personal-blog.personal-blog.svc.cluster.local:3000
```

The hostname routes to the `personal-blog` service HTTP port.

Required out-of-band secrets:

The image pull credential is the namespace-scoped `harbor-registry`
dockerconfigjson Secret for `registry.home`, backed by
`robot-namespace-personal-blog`.

```bash
kubectl create namespace personal-blog --dry-run=client -o yaml | kubectl apply -f -

kubectl -n personal-blog create secret generic personal-blog-runtime \
  --from-env-file=/path/to/pruned/.env.local
```

The runtime env file must include only secret values such as
`SANITY_REVALIDATE_SECRET`. Use the same value as the Sanity webhook secret.
Non-secret runtime settings are tracked in the `personal-blog` ConfigMap.
Updating this Secret should trigger Reloader in this namespace; otherwise, roll
the Deployment after the Secret update.

Do not commit secret runtime environment values.

## Sanity Revalidation Webhook

Create a Sanity webhook that calls the public app endpoint:

```text
POST https://blog.abhimanyu-saharan.com/api/revalidate
```

Set the webhook secret to the same value stored in
`personal-blog-runtime[SANITY_REVALIDATE_SECRET]`. The app validates Sanity's
`sanity-webhook-signature` header, revalidates the local pod, then fans the same
revalidation request out to every ready pod behind
`personal-blog-headless.personal-blog.svc.cluster.local`.

Use this projection so the app can revalidate the changed post and affected
category pages precisely:

```groq
{
  "_id": _id,
  "_type": _type,
  "slug": select(
    _type == "blog.post" => metadata.slug.current,
    _type == "page" => metadata.slug.current,
    slug.current
  ),
  "language": language,
  "categories": categories[]->slug.current
}
```

Recommended webhook filter:

```groq
_type in ["blog.post", "blog.category", "page"]
```
