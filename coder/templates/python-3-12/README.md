# Python 3.12 Development Workspace

This Coder template creates one ARM64 Kubernetes Pod per running workspace in
the `coder-workspaces` namespace. Each workspace gets a persistent
Longhorn-backed `/home/<workspace-owner>` volume and a PyCharm Toolbox
launcher.

The ARM64 workspace image is built from
`coder/templates/python-3-12/image/Dockerfile` and published to:

```text
ghcr.io/abhi1693/home-lab:python-3-12-13052026
```

The GitHub Actions workflow at
`.github/workflows/coder-ubuntu-desktop-image.yml` publishes the moving
`python-3-12` tag, date-stamped tags such as `python-3-12-13052026`, and
commit-SHA tags for `linux/arm64` when image files change. The template
defaults to a date-stamped tag and uses Kubernetes `IfNotPresent` pull policy so
workspace restarts reuse the node-local image cache.
The image inherits common OS tooling and the Codex package from the
commit-matched `coder-base` image, then installs Python-specific native
dependencies, Node.js 22, and uv on top.

Push the template after logging in to Coder:

```sh
coder login https://coder.home
coder templates push python-3-12 -d coder/templates/python-3-12
```

If the GHCR package is private, create an image pull secret in the workspace
namespace and pass its name when pushing the template:

```sh
kubectl -n coder-workspaces create secret docker-registry ghcr-home-lab \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-token>

coder templates push python-3-12 -d coder/templates/python-3-12 \
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
  source, and IDE state belong to the owner user instead of the image default.
- Containers allow privilege escalation for sudo-based setup scripts while still
  avoiding fully privileged pods.
- PVC ownership uses Kubernetes `OnRootMismatch` fsGroup handling to avoid
  repeated recursive permission walks on Longhorn volumes.
- The pod sets the usual user shell environment and defaults new shells to zsh
  after the Coder-specific dotfiles installer has run.
- Docker can be enabled per workspace with the `Docker Sidecar` parameter. When
  enabled, a privileged `docker:dind` sidecar runs in the workspace pod and the
  dev container gets `DOCKER_HOST=tcp://localhost:2375`. The dotfiles installer
  installs Docker client tooling: `docker`, Buildx, and Compose. When disabled,
  the sidecar, Docker volume, Docker env, and Docker client install are skipped.
- PostgreSQL and Redis can be enabled per workspace with boolean toggles only.
  PostgreSQL is a single-instance CloudNativePG cluster with an internal
  generated credential, and Redis is a standalone private pod with an internal
  generated password. Their generated secrets are attached to the workspace pod
  as environment sources when each service is enabled.
- The workspace image is fixed by the template owner. CPU, memory, home disk
  size, Docker sidecar availability, and optional service availability remain
  user-adjustable.
- The workspace image bakes in OS-level base tooling and Python-focused
  development prerequisites: Python runtime tooling, `venv`, `pip`, `pipx`,
  native build tools, PostgreSQL client headers for `pg_config`, and common
  headers used by Python packages such as Pillow, lxml, LDAP, and crypto
  libraries. It also includes `uv`/`uvx`. Project Python requirements are left
  to the cloned repository workflow.
- Node.js 22 and the OpenAI Codex CLI are baked into the image so npm-backed
  workspace tools are always available. The Node.js/Codex shell bootstrap links
  image-provided `node`, `npm`, `npx`, `corepack`, and `codex` into the
  workspace user's `~/.local/bin`.
- Workspace parameters are ordered by setup source first, workspace sizing
  second, optional Docker third, and optional services last.
- CPU and memory are configured as burst limits. Workspaces request `500m` CPU
  and `512Mi` memory for scheduling so they can still fit on a busy ARM64
  home-lab cluster.
- The built-in VS Code Desktop launcher is disabled; SSH, port forwarding, and
  web terminal helpers remain available.
- PyCharm Professional `2026.1.1` is preloaded into the persistent home volume
  on first workspace start and registered for JetBrains Gateway/Toolbox, so
  restarts do not reinstall the IDE backend.
- PyCharm setup and Node.js/Codex shell bootstrap are shared with the Node.js
  template through vendored scripts from `coder/templates/_shared`. Run
  `coder/templates/sync-shared.sh` after changing shared behavior and
  `coder/templates/check-shared.sh` before pushing.
- Registry modules provide a PyCharm Toolbox launcher, File Browser for the
  workspace home directory, Git identity environment configured from the Coder
  user profile, commit signing with the Coder SSH key, Node.js 22 for Python
  projects with frontend or static-asset dependencies, optional repository
  cloning, dotfiles defaulted to
  `https://github.com/abhi1693/dotfiles-coder` on branch `master`, automatic
  Coder CLI login.
- Repository cloning uses the official `coder/git-clone` module and follows the
  repository default branch or a branch parsed from a `/tree/` URL.
- GitHub HTTPS repository cloning uses Coder external auth provider `github`
  when the repository URL starts with `https://github.com/`.
- Defaults are small for idle home-lab use: `1` CPU core and `1Gi` memory.
  Increase CPU and memory for heavier JetBrains sessions.

When enabled, Docker daemon state lives in an ephemeral `emptyDir` volume and is
cleared when the workspace pod is rebuilt. Source code and IDE state remain on
the persistent home PVC.
