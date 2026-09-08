# Node.js 22 LTS Development Workspace

This Coder template creates one ARM64 Kubernetes Pod per running workspace in
the `coder-workspaces` namespace. Each workspace gets a persistent
Longhorn-backed `/home/<workspace-owner>` volume, Node.js 22 LTS tooling,
a PyCharm Toolbox launcher, and optional Docker-in-Docker.

The ARM64 workspace image is built from
`coder/templates/nodejs-22/image/Dockerfile` and published to:

```text
ghcr.io/abhi1693/home-lab:nodejs-22-13052026
```

The GitHub Actions workflow at
`.github/workflows/coder-ubuntu-desktop-image.yml` publishes the moving
`nodejs-22` tag, date-stamped tags such as `nodejs-22-13052026`, and commit-SHA
tags for `linux/arm64` when image files change. The template defaults to a
date-stamped tag and uses Kubernetes `IfNotPresent` pull policy so workspace
restarts reuse the node-local image cache.
The image inherits common OS tooling and the Codex package from the
commit-matched `coder-base` image, then installs only Node.js 22 on top.

Push the template after logging in to Coder:

```sh
coder login https://coder.home
coder templates push nodejs-22 -d coder/templates/nodejs-22
```

If the GHCR package is private, create an image pull secret in the workspace
namespace and pass its name when pushing the template:

```sh
kubectl -n coder-workspaces create secret docker-registry ghcr-home-lab \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-token>

coder templates push nodejs-22 -d coder/templates/nodejs-22 \
  -var image_pull_secret=ghcr-home-lab
```

## Operations

See [shared Node.js workspace operations](../README.md#nodejs-workspace-operations)
for storage, identity, Docker, IDE setup, Git authentication, and resource defaults.
