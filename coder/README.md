# Coder

This directory owns the Coder workspace template source for the lab.

## What It Provides

The templates create ARM64 Kubernetes workspaces for development tasks such as
Node.js, Python, NetBox plugin work, and Ubuntu desktop sessions. Each template
is self-contained because Coder uploads only the selected template directory
when `coder templates push -d <template-dir>` runs.

## Directory Map

| Path | Purpose |
| --- | --- |
| `templates/` | Template catalog, Terraform definitions, shared scripts, and image Dockerfiles. |
| `templates/_shared/` | Canonical shell setup scripts copied into every template. |
| `templates/base/image/` | Shared base image Dockerfiles and helper scripts. |
| `templates/<template>/` | One pushable Coder template. |

## How It Fits The Lab

Coder uses the same Kubernetes and storage primitives as the rest of the lab:

- workspace pods run on the K3s cluster;
- workspace home directories use persistent Kubernetes storage;
- ARM64 images are built from repo-owned Dockerfiles;
- optional services such as PostgreSQL or Redis-style containers are described
  in Terraform;
- template metadata is applied through helper scripts rather than hidden UI
  state.

See [templates/README.md](templates/README.md) for the full template catalog and
push flow.
