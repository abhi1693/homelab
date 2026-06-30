# Development Project

The Development project is reserved for development-facing workloads.

At the moment, there are no active Development app bundles tracked by Fleet.
The project metadata exists so the namespace and Rancher project boundary are
ready when Coder or other development services are moved into Fleet-managed
Kubernetes app bundles.

## Why This Project Exists

Development workloads have different lifecycle expectations than production or
home-automation services:

- workspaces may be short-lived;
- resource usage can be bursty;
- user storage has different durability expectations;
- image builds and toolchains change more frequently;
- access control often follows developer identity rather than app identity.

Keeping this project separate prevents development experiments from blending
into system, database, or public application concerns.

## Current Coupling

Most development workspace source currently lives under `coder/templates/`.
Those templates produce Coder workspaces that run on Kubernetes, use ARM64
images, and can mount persistent storage. If development runtime apps are added
later, this project is the expected place for their Fleet bundles.

## Operating Model

Make desired-state changes in Git and let Fleet reconcile them. Keep template
source in `coder/templates/` unless the change is a Kubernetes app bundle that
belongs in this project.
