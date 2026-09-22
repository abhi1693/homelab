# Personal Blog

Fleet-managed deployment for the personal blog.

The custom Deployment retains two ReplicaSet revisions; Git and Fleet history
remain the primary rollback path.

The public hostname is `blog.abhimanyu-saharan.com`.

The deployment pins release `0.3.17` from
`registry.home/ghcr.io/abhi1693/personal-blog` (Linux/ARM64).
It serves the RFC 4287 Atom feed at `/posts/atom.xml` and preserves the RSS 2.0
feed at `/posts/rss.xml`, including existing RSS GUIDs and publication dates.
Both feeds are advertised by page metadata and revalidated on Sanity changes.

Release images are built by the source repository's Container workflow and
pulled through the `registry.home` GHCR cache. After updating the image pin,
verify matching ARM64 digests, Fleet desired/applied deployment IDs, workload
readiness, and both public feed responses. Roll back this release by reverting
the image pin to `0.3.16` in Git and allowing Fleet to reconcile it.

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

The web container requests 50m CPU, with its existing burst capacity retained.
The [September 19 resource review](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-09-19-cpu-sizing-review)
records the seven-day usage and rollout checks.
