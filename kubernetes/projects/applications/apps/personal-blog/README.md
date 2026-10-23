# Personal Blog

Fleet-managed deployment for the personal blog.

The custom Deployment retains two ReplicaSet revisions; Git and Fleet history
remain the primary rollback path.

The public hostname is `blog.abhimanyu-saharan.com`.

The deployment pins release `0.3.18` and its immutable index from
`registry.home/ghcr.io/abhi1693/personal-blog` (Linux/ARM64), using Node.js
26.12.1 and Next.js 16.4.2 with packaged application and Faro version defaults.
It serves the RFC 4287 Atom feed at `/posts/atom.xml` and preserves the RSS 2.0
feed at `/posts/rss.xml`, including existing RSS GUIDs and publication dates.
Both feeds are advertised by page metadata and revalidated on Sanity changes.

Release images are built by the source repository's Container workflow and
pulled through the `registry.home` GHCR cache. Image automation uses the upstream
`ghcr.io/abhi1693/personal-blog` Docker datasource and its existing enabled branch
update policy. A GitHub release starts the build and is not evidence that the
image exists. Require production CMS generation at the exact tested source;
cached publication must prove reuse of that tested runtime filesystem. Fresh
native SBOM, strict scan and runtime gates remain required. Verify the source,
ARM64 index/config and
signed GitHub attestation before accepting deployment. The policy guard rejects
source-release tracking or loss of explicit registry coverage. After updating the image pin,
verify matching ARM64 digests, Fleet desired/applied deployment IDs, workload
readiness, and both public feed responses. For a rollback, use the last accepted
immutable image through Git and Fleet while retaining the new credentials and
credential revision. Never restore exposed credentials. Follow the credential
cutover runbook below to verify propagation and retire the old provider key.

The app-owned Cloudflare Tunnel ingress and service are both named
`personal-blog` in the `personal-blog` namespace. Cloudflare serves public HTTPS,
the tunnel transport is encrypted, and the final in-cluster hop to the app pods
uses HTTP:

```text
http://personal-blog.personal-blog.svc.cluster.local:3000
```

The hostname routes to the `personal-blog` service HTTP port.

## Runtime credentials

Fleet manages `SopsSecret/personal-blog-secrets` in the `personal-blog` namespace.
Its single encrypted `Opaque` template materializes `Secret/personal-blog`, which
the web Deployment consumes through `envFrom`. The newsletter CronJob reads the
same Secret's `CRON_SECRET` field. `harbor-registry` remains the separate encrypted
image pull credential; do not copy registry or unrelated credentials into the
application Secret.

Use the [credential cutover runbook](../../../../../docs/runbooks/personal-blog-credential-cutover.md)
and its staged, tested helper for Resend/CRON rotation. It first verifies the
actual SOPS recipient with synthetic data, encrypts one-time provider responses
in private recovery storage, and prepares two permanent GitOps changes: the
Secret, then the verified image and credential revision. Actual Secret and new
Pod environment values are compared privately before old-key retirement. No
manual Secret mutation, restart, Job or temporary scaling is required.
Rollout preparation preserves the image's Renovate comment and unrelated YAML;
parsed equality checks reject edits beyond the image and credential revision.
Provider calls identify this maintenance client and request JSON explicitly;
metadata rejection stops capture before any credential creation or propagation.
Old-key retirement requires removal from the complete account key list and the
provider's documented invalid-key response; generic HTTP failures cannot pass.

Sanity's required Viewer token, Studio and authenticated Draft Mode preview stay
intact. Its rotation is blocked until a fresh privileged project recovery session
is verified; the saved owner session returned 401. Resend's previously failed
sender-domain status is a newsletter limitation, not a claim about web readiness.

## Sanity Revalidation Webhook

Create a Sanity webhook that calls the public app endpoint:

```text
POST https://blog.abhimanyu-saharan.com/api/revalidate
```

Set the webhook secret to the same value stored in
`personal-blog[SANITY_REVALIDATE_SECRET]`. The app validates Sanity's
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

The web container requests 100m CPU, with its existing burst capacity retained.
The [September 19 resource review](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-09-19-cpu-sizing-review)
records the seven-day usage and rollout checks.
