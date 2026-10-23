---
title: Wardn AI Website
---

# Wardn AI Website

Fleet-managed deployment for the public Wardn AI product website at
`https://wardnai.dev`.

The website follows the existing Wardn frontend deployment contract: a
Next.js standalone server on port `3000`, one Linux/ARM64 replica, the
`registry.home` GHCR pull-through cache, and the namespace-scoped
`harbor-registry` image pull Secret.

The bundle uses the shared `wardn` namespace and depends on `wardn-hub`, which
owns that namespace, the registry Secret, and the namespace-wide default-deny
NetworkPolicy. Its app-local NetworkPolicy allows only the controlled
Cloudflare connector to reach the website service.

Git and Fleet history are the primary rollback path; the Deployment retains
two ReplicaSet revisions.

The website requests `10m` CPU without a CPU limit. Recheck this small
reservation against sustained public traffic before treating it as a stable
capacity baseline.

## Upgrades

Track published Docker tags and digests, since a GitHub release starts the image
build. Require source CI and native ARM64 runtime validation before publishing
the patch release. Verify the release image's strict vulnerability/secret scan,
SBOM, provenance, exact source revision and immutable digest before changing
the pin in `deployment.yaml`.

The source workflow checks non-root identity, package/OCI version parity, real
HTTP and built assets, native Sharp image processing and the Next.js optimizer
and cache. After Fleet reconciles, require matching desired/applied IDs, a ready
replacement with zero restarts, the expected runtime image and public route and
asset checks. Keep the shared namespace/Hub ownership and paused Wardn services
unchanged. Complete these checks before upgrading another application.

For GitHub attestation verification, set `image_digest`, `source_commit` and
`release_tag` to the verified release values. Require both this source repository
and the shared workflow that signs its images:

```bash
gh attestation verify "oci://ghcr.io/abhi1693/wardn-ai-website@${image_digest:?}" \
  --repo abhi1693/wardn-ai-website \
  --signer-workflow abhi1693/actions/.github/workflows/container-images.yml \
  --source-digest "${source_commit:?}" --source-ref "refs/tags/${release_tag:?}"
```
