# NetBox Infrastructure Workspace

This directory is reserved for infrastructure source-of-truth workflows related
to NetBox.

The live NetBox application is declared under:

```text
kubernetes/projects/home-automation/apps/netbox/
```

That app bundle owns the Kubernetes deployment, Helm values, storage, ingress,
plugins, and database wiring. This infrastructure directory exists for artifacts
that are not themselves Kubernetes app desired state, for example:

- future NetBox import/export helpers;
- generated inventory or IPAM reports;
- source-of-truth migration notes;
- scripts that reconcile infrastructure data into NetBox.

Keep Kubernetes manifests with the NetBox app bundle. Keep reusable
source-of-truth tooling here.
