# Kubernetes Desired State

This directory owns the desired state that Rancher Fleet reconciles after the
Ansible bootstrap has created a working K3s cluster.

## What This Directory Owns

| Path | Purpose |
| --- | --- |
| `fleet/` | Fleet control-plane bundles and GitRepo resources. |
| `projects/` | Rancher project metadata and project-scoped app bundles. |
| `images/` | Custom image definitions, patches, and image documentation. |

## Why This Directory Exists

The bootstrap layer creates the cluster, but this directory defines what the
cluster continuously runs. It is the long-lived GitOps state for:

- system services such as monitoring, logging, tracing, DNS, backup, and
  compliance;
- shared platform services such as PostgreSQL, Valkey, and Harbor;
- public and internal applications;
- media and home automation workloads;
- project boundaries, namespace ownership, and app-level policy.

Fleet watches explicit paths and reconciles them into the cluster. This keeps
application operations separate from host bootstrap.

## How Fleet Reads This Tree

The Fleet control-plane bundle creates one GitRepo per major project. Each
GitRepo lists the app paths it owns:

```mermaid
flowchart TD
  bundle["kubernetes/fleet/fleet-project-gitrepos"]
  bundle --> applications["applications-gitrepo.yaml"]
  bundle --> database["database-gitrepo.yaml"]
  bundle --> entertainment["entertainment-gitrepo.yaml"]
  bundle --> homeAutomation["home-automation-gitrepo.yaml"]
  bundle --> system["system-gitrepo.yaml"]
  bundle --> rancherProjects["rancher-projects-gitrepo.yaml"]

  applications --> applicationsApps["kubernetes/projects/applications/apps"]
  database --> databaseApps["kubernetes/projects/database/apps"]
  entertainment --> entertainmentApps["kubernetes/projects/entertainment/apps"]
  homeAutomation --> homeApps["kubernetes/projects/home-automation/apps"]
  system --> systemApps["kubernetes/projects/system/apps"]
  rancherProjects --> projectMetadata["kubernetes/projects/*/_project"]
```

This split matters because app projects have different dependencies and
different failure domains. A Database reconciliation problem should not hide in
the same bundle as a media app or a public web app.

## Bundle Shape

Most app directories follow this pattern:

| File | Role |
| --- | --- |
| `fleet.yaml` | Fleet bundle metadata, dependencies, namespace defaults, and ImageScan configuration. |
| `deployment*.yaml` / `cronjob*.yaml` / `job*.yaml` | Workload definitions. |
| `service*.yaml` / `ingress*.yaml` | East-west service discovery and north-south entry points. |
| `networkpolicy*.yaml` / `*-cnp.yaml` | Allowed traffic paths. |
| `pvc*.yaml` / storage files | Persistent storage declarations. |
| `values.yaml` / `helmop.yaml` | Helm chart configuration through Fleet HelmOps. |
| `README.md` | App-specific purpose, dependencies, secrets, and operating notes. |

## HelmOps Pattern

For upstream Helm charts, this repo prefers a small GitOps wrapper bundle that
declares:

- the `HelmOp`;
- values in Git;
- supporting ConfigMaps or Kustomize configuration;
- network policies, dashboards, or extra resources around the chart.

This keeps chart installation declarative while preserving app-local context.

## Fleet ImageScan

Fleet ImageScan is enabled through Rancher/Fleet configuration and selected
project GitRepos. Workloads use marker comments so Fleet can update image tags
in Git:

```yaml
image: registry.home/example-project/example-app:0.1.0 # {"$imagescan": "example-app"}
```

ImageScan should update source files, not mutate live workloads directly. App
image pipelines should publish semver-style tags when Fleet is expected to
select newer versions.

## Operating Model

For normal changes:

1. Edit the owning app bundle under `kubernetes/projects/<project>/apps/<app>/`.
2. Validate locally or with server-side dry run when possible.
3. Commit and push.
4. Let Fleet reconcile the bundle.
5. Use read-only cluster inspection to diagnose convergence.

Avoid direct `kubectl apply`, `helm upgrade`, or manual patching unless it is a
deliberate break-glass action.
