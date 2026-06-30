# Development Project

The Rancher project object is tracked separately from
`kubernetes/projects/development/_project` by `home-lab-rancher-projects`.
Project metadata uses non-forcing drift correction because Rancher `Project`
objects include immutable fields.

There are no active Development workloads tracked by Fleet right now.

## Operating Model

Make desired-state changes in Git and let Fleet reconcile them. Direct cluster
changes should be limited to resources Fleet cannot own, such as manually
provisioned secrets, or to fixing ownership metadata so Fleet can take over.
