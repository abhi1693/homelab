# Infrastructure

This directory owns the non-application infrastructure for the home lab. It is
the boundary between physical hosts, network assumptions, bootstrap automation,
and the Kubernetes desired state that takes over after the cluster is running.

## What Lives Here

| Path | Purpose |
| --- | --- |
| `ansible/` | Host preparation and K3s bootstrap automation. |
| `network/` | Router-side and network-adjacent notes that cannot be reconciled by Kubernetes. |
| `netbox/` | Reserved space for infrastructure source-of-truth exports, imports, or generated NetBox artifacts. |
| `patches/` | Reserved space for infrastructure-level patches that do not belong to an app image. |

## Why This Exists

Kubernetes cannot bootstrap itself from bare Raspberry Pi nodes. The
infrastructure layer handles the work that must happen before Rancher Fleet can
reconcile application bundles:

- OS and Raspberry Pi node preparation.
- K3s server and agent installation.
- Stable Kubernetes API registration through kube-vip.
- Cilium installation, LoadBalancer IPAM, and BGP service advertisement.
- Longhorn, Rancher, cert-manager, and Fleet bootstrap.
- Host-level exporters and operational services that are not best managed as
  ordinary app manifests.

Once this layer is healthy, day-to-day desired state moves to `kubernetes/`.

## How It Fits Together

1. `infrastructure/ansible/playbooks/site.yml` runs the bootstrap roles in the
   expected order.
2. K3s forms the cluster using server and agent configuration from Ansible
   templates.
3. kube-vip provides a stable Kubernetes API endpoint for additional nodes.
4. Cilium replaces the default networking path and adds policy, service IPAM,
   and BGP advertisement.
5. Rancher and Fleet are installed so the cluster can reconcile Git-managed
   application state.
6. The `kubernetes/` tree becomes the normal place for platform and app
   changes.

## Public Versus Environment-Specific State

The reusable parts are roles, playbooks, templates, and documented patterns.
The environment-specific parts are inventory, secrets, router config, IP
addresses, domains, and credentials. Those values should be supplied by the
operator for their own lab.
