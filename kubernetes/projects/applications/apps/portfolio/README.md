---
title: Portfolio
---

# Portfolio

Fleet-managed deployment for the `abhi1693/portfolio` standalone Next.js
application.

The custom Deployment retains two ReplicaSet revisions; Git and Fleet history
remain the primary rollback path.

The web container requests `10m` CPU without a CPU limit. Verify the public
route after Fleet rolls the pod.

## Upgrades

Track published Docker image tags and digests from `ghcr.io/abhi1693/portfolio`.
A GitHub release starts image publication, so its release event alone is not
evidence that the image is available. Renovate must wait for the published
container before proposing an update.

After source CI passes, publish the next patch release through the repository's
native ARM64 container workflow. Require its vulnerability scan, SBOM, and
provenance checks before pinning the semver tag and verified digest in
`deployment.yaml`. Keep the registry proxy prefix and runtime security settings.

Source PRs and release builds must both validate the native image, including
non-root identity, locked runtime versions, real HTTP and static assets, Sharp,
and the Next.js image optimizer. The standalone runtime uses a consistent Alpine
base and omits unused global package managers. A failed image publication needs
a new patch release; do not retarget its published source tag or bypass its scan.

Wait for Fleet's desired and applied bundle IDs to match, then verify the new
pod's image digest, ARM64 runtime, readiness, restart count, both public hosts,
and the actual JavaScript/CSS assets referenced by their HTML. Complete these
checks before upgrading another app. Roll back through Git to the previous
verified image if the replacement fails these checks.

## Runtime Dependencies

- Namespace-scoped `harbor-registry` image pull Secret for `registry.home`,
  backed by `robot-namespace-portfolio`.
- Cloudflare Tunnel ingress for `abhimanyu-saharan.com` and
  `www.abhimanyu-saharan.com`.
