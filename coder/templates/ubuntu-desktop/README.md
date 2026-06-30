# Ubuntu Desktop Workspace

This Coder template creates one ARM64 Ubuntu desktop Pod per running workspace
in the `coder-workspaces` namespace. Each workspace gets a persistent
Longhorn-backed `/home/<workspace-owner>` volume, an XFCE desktop exposed
through Coder Portable Desktop, Node.js 24, and the OpenAI Codex CLI installed
as `codex`.

The ARM64-only workspace image is built from
`coder/templates/ubuntu-desktop/image/Dockerfile`, extends the commit-matched
`coder-desktop-base` image, and is published to:

```text
ghcr.io/abhi1693/home-lab:ubuntu-desktop-13052026
```

The GitHub Actions workflow at
`.github/workflows/coder-ubuntu-desktop-image.yml` publishes the moving
`ubuntu-desktop` tag, date-stamped tags such as `ubuntu-desktop-13052026`, and
commit-SHA tags for `linux/arm64` when the image files change. The template
defaults to a date-stamped tag and uses Kubernetes `IfNotPresent` pull policy so
workspace restarts reuse the node-local image cache.

Push the template after logging in to Coder:

```sh
coder login https://coder.home
coder templates push ubuntu-desktop -d coder/templates/ubuntu-desktop
```

If the GHCR package is private, create an image pull secret in the workspace
namespace and pass its name when pushing the template:

```sh
kubectl -n coder-workspaces create secret docker-registry ghcr-home-lab \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-token>

coder templates push ubuntu-desktop -d coder/templates/ubuntu-desktop \
  -var image_pull_secret=ghcr-home-lab
```

Open the `Desktop` app from the workspace page to use the browser viewer. The
viewer is served by `portabledesktop viewer` on `127.0.0.1:6080` inside the
workspace and is proxied through Coder with workspace app subdomains.

Operational choices:

- Workspaces run as direct Kubernetes Pods because the template does not need
  Deployment rollout or replica management.
- The desktop container uses a date-tagged GHCR image with `IfNotPresent`
  pull policy to avoid pulling the image on every workspace start.
- Each workspace uses one persistent Longhorn home PVC mounted `ReadWriteOnce`.
- Workspace pods are scheduled to ARM64 nodes and do not mount a Kubernetes
  service account token.
- Containers bootstrap as the image's `coder` user, create a per-owner
  workspace user at UID `1001`, then run the Coder agent as that owner user.
- The persistent home PVC is mounted at `/home/<workspace-owner>` so shell,
  source, Portable Desktop runtime state, and Codex state belong to the owner
  user instead of the image default.
- Coder Portable Desktop `v0.0.8` is baked into the image as
  `/usr/local/bin/portabledesktop`. The startup script still has a pinned
  checksum-verified download fallback if the binary is missing.
- The repo-owned `coder-desktop-base` image extends upstream
  `codercom/enterprise-desktop`, installs XFCE dependencies, common desktop
  utilities, general development packages, zsh, and the OpenAI Codex package.
  The final workspace image adds only Node.js 24 and Portable Desktop, so
  workspace startup does not depend on `apt-get`, nvm, or npm installs.
- The Portable Desktop session state is stored under
  `~/.cache/portabledesktop`, and the browser viewer listens only on
  `127.0.0.1:6080` inside the workspace.
- Docker can be enabled per workspace with the `Docker Sidecar` parameter. When
  enabled, a privileged `docker:dind` sidecar runs in the workspace pod and the
  desktop container gets `DOCKER_HOST=tcp://localhost:2375`. The dotfiles
  installer installs Docker client tooling. When disabled, the sidecar, Docker
  volume, Docker env, and Docker client install are skipped.
- Registry modules provide File Browser for the workspace home directory, Git
  identity environment configured from the Coder user profile, commit signing
  with the Coder SSH key, optional dotfiles, and automatic Coder CLI login.
- Defaults are sized for a lightweight desktop: `2` CPU cores, `4Gi` memory,
  and a `40Gi` home disk. Increase CPU and memory for browser-heavy or
  language-server sessions.

When enabled, Docker daemon state lives in an ephemeral `emptyDir` volume and is
cleared when the workspace pod is rebuilt. Source code, user tooling, desktop
settings, and Codex state remain on the persistent home PVC.
