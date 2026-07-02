# Custom Images

This directory contains image definitions that are owned by the repository.

## Why Images Live Here

Some workloads need more than a stock upstream image:

- upstream images may not publish ARM64 manifests;
- plugins may need to be baked into an image for repeatable startup;
- local patches may be required;
- image build inputs should be reviewed next to the workload that consumes
  them.

Keeping Dockerfiles and patches in Git makes image behavior auditable. Custom
image pipelines publish versioned tags to their source registry, usually GHCR,
Renovate reads those tags from the upstream `depName`, and workloads pull the
same artifact through Harbor with a `registry.home/<registry>/<repo>:<tag>`
image path.

## Image Areas

| Path | Purpose |
| --- | --- |
| `jellyfin/` | Jellyfin image customization, plugin metadata, and PostgreSQL-oriented patch work. |
| `netbox/` | NetBox image customization and pinned plugin requirements. |

## Coupling With Apps

Image definitions here are consumed by app bundles under `kubernetes/projects/`.
For example:

- Jellyfin app manifests reference the custom Jellyfin image.
- NetBox Helm values reference the custom NetBox image with baked plugins.
The image directory should document how the image is built and why it exists.
The app directory should document how the running workload uses it.
