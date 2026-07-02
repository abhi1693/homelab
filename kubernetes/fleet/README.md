# Fleet Control Plane

This directory contains Fleet bundles that manage Fleet itself and the project
GitRepo resources that point back to this repository.

## What Lives Here

| Path | Purpose |
| --- | --- |
| `fleet-project-gitrepos/` | GitRepo resources for Rancher projects and app bundles. |
| `fleet-gitjob-webhook/` | Webhook support for Fleet GitJob behavior. |

## Why This Exists

The `kubernetes/projects/` tree contains the desired state for apps and
platform services, but Fleet needs GitRepo resources before it can reconcile
those paths. This directory is the control-plane bridge between the bootstrap
layer and the project app bundles.

## How It Works

1. Ansible installs Rancher and Fleet.
2. The `fleet_apps` role creates the first Fleet GitRepo bundle.
3. Fleet reads the GitRepo resources in this directory.
4. Each project GitRepo points to explicit app paths under
   `kubernetes/projects/<project>/apps/`.
5. Fleet creates child bundles for those paths and reconciles them.

## Project GitRepos

| GitRepo | Scope |
| --- | --- |
| `home-lab-rancher-projects` | Rancher project metadata under `kubernetes/projects/*/_project`. |
| `home-lab-system` | System services and platform add-ons. |
| `home-lab-database` | PostgreSQL, Valkey, operators, and database network policy. |
| `home-lab-applications` | Public and personal application workloads. |
| `home-lab-entertainment` | Media stack and entertainment automation. |
| `home-lab-home-automation` | Home Assistant, NetBox, rack automation, UPS monitoring, and Cloudflare tunnel controller. |

## Image Updates

Project GitRepos reconcile desired state only. Container image updates are
handled by the Renovate app bundle, which commits source changes back to this
repository for Fleet to reconcile.

Renovate reads upstream image tags from each manifest's `depName` comment.
Fleet then reconciles the updated manifest exactly as committed. Runtime image
pulls still go through Harbor when the image value starts with `registry.home/`,
for example `registry.home/ghcr.io/abhi1693/git-rank-backend:1.2.28`.
