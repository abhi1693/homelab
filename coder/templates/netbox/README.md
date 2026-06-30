# NetBox 4.6 Development Workspace

This Coder template creates an ARM64 Kubernetes workspace for NetBox plugin
development. It defaults the NetBox runtime checkout to the official NetBox
GitHub repo at `https://github.com/netbox-community/netbox/tree/v4.6.0` and the
editable plugin checkout to
`https://github.com/Onemind-Services-LLC/netbox-metatype-importer`.

The workspace runs in the `coder-workspaces` namespace with a persistent
Longhorn-backed `/home/<workspace-owner>` volume, PyCharm Gateway, File
Browser, a private PostgreSQL database, a private Redis instance, a runnable
NetBox dev server, and an editable plugin install.

The ARM64 workspace image is built from
`coder/templates/netbox/image/Dockerfile` and published to:

```text
ghcr.io/abhi1693/home-lab:netbox-16052026
```

The GitHub Actions workflow at
`.github/workflows/coder-ubuntu-desktop-image.yml` publishes the moving
`netbox` tag, date-stamped tags such as `netbox-16052026`, and commit-SHA tags
for `linux/arm64` when image files change. The template defaults to a
date-stamped tag and uses Kubernetes `IfNotPresent` pull policy so workspace
restarts reuse the node-local image cache.

Push the template after logging in to Coder:

```sh
coder login https://coder.home
coder templates push netbox -d coder/templates/netbox
```

If the GHCR package is private, create an image pull secret in the workspace
namespace and pass its name when pushing the template:

```sh
kubectl -n coder-workspaces create secret docker-registry ghcr-home-lab \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-token>

coder templates push netbox -d coder/templates/netbox \
  -var image_pull_secret=ghcr-home-lab
```

Operational choices:

- The template derives from the Python 3.12 services workspace and keeps the
  same direct Kubernetes Pod model, persistent home PVC, PyCharm setup, Git
  identity, commit signing, File Browser, dotfiles, and optional Docker
  sidecar behavior.
- PostgreSQL and Redis default to enabled because NetBox requires them. The
  PostgreSQL database and username are both `netbox`; the password is generated
  per workspace and injected through a Kubernetes Secret.
- First workspace start waits for the official NetBox repository clone, clones
  the plugin into `~/plugins/netbox-metatype-importer`, checks out or creates
  the local `netbox-4.6-compat` work branch from `dev`, creates
  `~/.venv/netbox`, installs NetBox requirements, installs the plugin with
  `pip install -e`, writes `netbox/netbox/configuration.py`, runs migrations,
  runs `manage.py check`, and creates a per-owner superuser.
- The generated NetBox config enables the editable plugin in `PLUGINS` and
  includes default `PLUGINS_CONFIG` for `netbox_metatype_importer`. The GitHub
  token defaults to an empty string so NetBox can boot; set
  `NETBOX_METATYPE_GITHUB_TOKEN` in the workspace before importing from GitHub.
- If the remote plugin work branch does not exist yet, setup creates it locally
  from the configured base branch and applies the small NetBox 4.6 bootstrap
  compatibility patch needed for `netbox_metatype_importer`.
- The NetBox app starts `manage.py runserver 0.0.0.0:8000 --insecure
  --noreload` in the background and exposes it through the `NetBox` Coder app.
- The `Service Credentials` Coder app shows the NetBox URL, generated admin
  credentials, plugin checkout details, PostgreSQL connection details, and
  Redis connection details.
- The image bakes in Python build tooling and NetBox-oriented native
  dependencies: PostgreSQL client headers and CLI, Pillow/lxml/LDAP/crypto
  headers, Graphviz, libyaml, Node.js 22, Codex, uv, and uvx.
- Defaults are sized for NetBox development: `2` CPU cores, `4Gi` memory, and a
  `20Gi` home disk. CPU, memory, disk size, Docker sidecar, PostgreSQL, and
  Redis remain user-adjustable.
- The NetBox repository clone uses the official `coder/git-clone` module and
  follows the branch or tag parsed from the `/tree/` URL. Plugin cloning is
  handled by the setup script so it can maintain a separate editable work
  branch under `~/plugins`.

When enabled, Docker daemon state lives in an ephemeral `emptyDir` volume and is
cleared when the workspace pod is rebuilt. Source code, the Python virtualenv,
generated NetBox config, and IDE state remain on the persistent home PVC.
