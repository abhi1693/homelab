# Coder Templates

This directory contains the ARM64 Coder workspace templates used by the home
lab. Each template directory is self-contained because `coder templates push -d
<template-dir>` only uploads that directory.

## Template Catalog

| Directory | Template slug | Display name | Description |
| --- | --- | --- | --- |
| `nodejs-22/` | `nodejs-22` | Node.js 22 LTS | ARM64 Node.js 22 LTS workspace with Codex CLI, PyCharm Gateway, Longhorn home storage, and optional Docker sidecar. |
| `nodejs-24/` | `nodejs-24` | Node.js 24 LTS | ARM64 Node.js 24 LTS workspace with Codex CLI, PyCharm Gateway, Longhorn home storage, and optional Docker sidecar. |
| `nodejs-26/` | `nodejs-26` | Node.js 26 Current | ARM64 Node.js 26 Current workspace with Codex CLI, PyCharm Gateway, Longhorn home storage, and optional Docker sidecar. |
| `netbox/` | `netbox` | NetBox 4.6 Plugin Dev | ARM64 NetBox 4.6 plugin development workspace with the official NetBox repo, editable plugin checkout, PyCharm, PostgreSQL, Redis, and a dev-server app. |
| `python-3-12/` | `python-3-12` | Python 3.12 + Services | ARM64 Python 3.12 workspace with Codex CLI, uv, PyCharm Gateway, Longhorn storage, optional Docker, PostgreSQL, and Redis. |
| `ubuntu-desktop/` | `ubuntu-desktop` | Ubuntu Desktop | ARM64 Ubuntu desktop with XFCE via Portable Desktop, Codex CLI, Node.js 24, Longhorn home storage, and optional Docker. |

Template display names and descriptions live in Coder metadata, not Terraform.
Apply the canonical metadata after creating or renaming templates:

```sh
kubectl -n coder get secret coder-home-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/coder-home-ca.crt

CODER_CLIENT_TLS_CA_FILE=/tmp/coder-home-ca.crt \
  coder/templates/apply-metadata.sh
```

## Images

Images are published to `ghcr.io/abhi1693/home-lab` by
`.github/workflows/coder-ubuntu-desktop-image.yml` for `linux/arm64`.

The workflow publishes three tag families for every image:

- Moving tags such as `nodejs-24`.
- Date-stamped tags such as `nodejs-24-13052026`.
- Commit-SHA tags such as `nodejs-24-<short-sha>`.

Active templates default to date-stamped image tags from the last completed
GHCR build. Commit-SHA tags remain available for exact image rollback or audit,
and moving tags remain available for manual use.

Shared base image Dockerfiles live in `coder/templates/base/image/`. The
workflow publishes `coder-base` and `coder-desktop-base` first, then builds the
template images from commit-matched base layers. Final template Dockerfiles
require an explicit `BASE_IMAGE` build argument and use base-provided helper
scripts such as `install-node`, so local and CI builds fail instead of silently
falling back to a stale moving base tag.

Both base images also install the local `coder.home` CA certificate from
`coder/templates/base/image/coder-home-ca.crt` into the Ubuntu trust store. That
keeps Coder agent health checks, websocket probes, `curl`, Python requests, and
Node.js tooling able to trust `https://coder.home` without per-workspace
certificate bootstrapping in Terraform.

## Shared Scripts

Shared workspace bootstrap logic is canonical under `_shared/` and vendored
into each template with:

```sh
coder/templates/sync-shared.sh
```

Update `_shared/scripts/` first for behavior that should stay identical across
templates, including PyCharm backend setup and Node.js/Codex shell bootstrap.
Avoid editing `*/shared/scripts/` directly.

Run the drift check before pushing templates:

```sh
coder/templates/check-shared.sh
```

## Validation

Run Terraform formatting and validation for every template directory:

```sh
terraform -chdir=coder/templates/nodejs-22 fmt -check
terraform -chdir=coder/templates/nodejs-22 validate
terraform -chdir=coder/templates/nodejs-24 fmt -check
terraform -chdir=coder/templates/nodejs-24 validate
terraform -chdir=coder/templates/nodejs-26 fmt -check
terraform -chdir=coder/templates/nodejs-26 validate
terraform -chdir=coder/templates/netbox fmt -check
terraform -chdir=coder/templates/netbox validate
terraform -chdir=coder/templates/python-3-12 fmt -check
terraform -chdir=coder/templates/python-3-12 validate
terraform -chdir=coder/templates/ubuntu-desktop fmt -check
terraform -chdir=coder/templates/ubuntu-desktop validate
```

`terraform validate` requires each template directory to have been initialized
with its provider/module cache.

## Push Flow

Log in to Coder and push each template from its own directory:

```sh
coder login https://coder.home

coder templates push nodejs-22 -d coder/templates/nodejs-22
coder templates push nodejs-24 -d coder/templates/nodejs-24
coder templates push nodejs-26 -d coder/templates/nodejs-26
coder templates push netbox -d coder/templates/netbox
coder templates push python-3-12 -d coder/templates/python-3-12
coder templates push ubuntu-desktop -d coder/templates/ubuntu-desktop
```

If the browser or CLI host does not trust the local Coder CA yet, pass
`CODER_CLIENT_TLS_CA_FILE` as shown in the metadata section.
