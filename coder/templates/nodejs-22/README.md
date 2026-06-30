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

Operational choices:

- Workspaces run as direct Kubernetes Pods because the template does not need
  Deployment rollout or replica management.
- Each workspace uses one persistent Longhorn home PVC mounted `ReadWriteOnce`.
- Workspace pods are scheduled to ARM64 nodes and do not mount a Kubernetes
  service account token.
- Containers bootstrap as the image's `coder` user, create a per-owner workspace
  user at UID `1001`, then run the Coder agent as that owner user.
- The persistent home PVC is mounted at `/home/<workspace-owner>` so shell,
  source, and editor state belong to the owner user instead of the image
  default.
- Docker can be enabled per workspace with the `Docker Sidecar` parameter. When
  enabled, a privileged `docker:dind` sidecar runs in the workspace pod and the
  dev container gets `DOCKER_HOST=tcp://localhost:2375`. The dotfiles installer
  installs Docker client tooling: `docker`, Buildx, and Compose. When disabled,
  the sidecar, Docker volume, Docker env, and Docker client install are skipped.
- The workspace image is fixed by the template owner. CPU, memory, home disk
  size, and Docker sidecar availability remain user-adjustable.
- Node.js 22 LTS and the OpenAI Codex CLI are baked into the workspace image.
  Use another `nodejs-*` template when a different Node.js major version is
  needed.
- PyCharm Professional `2026.1.1` is preloaded into the persistent home volume
  on first workspace start and registered for JetBrains Gateway/Toolbox, so
  restarts do not reinstall the IDE backend.
- PyCharm setup and Node.js/Codex shell bootstrap are shared with the Python
  template through vendored scripts from `coder/templates/_shared`. Run
  `coder/templates/sync-shared.sh` after changing shared behavior and
  `coder/templates/check-shared.sh` before pushing.
- The workspace image bakes in OS-level base tooling and native build
  prerequisites commonly needed by Node.js packages: Git, curl, jq, zsh, Python
  3, compiler tools, `pkg-config`, and OpenSSL headers.
- The Node.js/Codex shell bootstrap links image-provided `node`, `npm`, `npx`,
  `corepack`, and `codex` into the workspace user's `~/.local/bin`.
- Repository cloning uses the official `coder/git-clone` module and follows the
  repository default branch or a branch parsed from a `/tree/` URL.
- GitHub HTTPS repository cloning uses Coder external auth provider `github`
  when the repository URL starts with `https://github.com/`.
- Registry modules provide File Browser for the workspace home directory, Git
  identity environment configured from the Coder user profile, commit signing
  with the Coder SSH key, a PyCharm Toolbox launcher, optional repository
  cloning, dotfiles defaulted to `https://github.com/abhi1693/dotfiles-coder`
  on branch `master`, and automatic Coder CLI login.
- Defaults are small for idle home-lab use: `1` CPU core and `1Gi` memory.
  Increase CPU and memory for heavier build or language-server sessions.

When enabled, Docker daemon state lives in an ephemeral `emptyDir` volume and is
cleared when the workspace pod is rebuilt. Source code, user tooling, and IDE
state remain on the persistent home PVC.
