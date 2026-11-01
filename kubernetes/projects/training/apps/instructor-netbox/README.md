# Instructor NetBox

Official community chart 8.3.98 runs NetBox 4.7.4 on ARM64 at https://instructor.netbox.home in the Training project. One web and one worker use shared HA PostgreSQL and Valkey. The retained database is `netbox_instructor`; task/cache DB indexes 12/13 are reserved for this lab. Media is ephemeral (`emptyDir`); no media PVC is required.

Credentials are SOPS-managed in instructor-prerequisites. Retrieve the bootstrap password from Secret `instructor-netbox-admin`, key `password`, through an authorized local Kubernetes client. The namespace is owned by instructor-prerequisites.

All runtime, init, waiter and chart-test images pull through the `registry.home` proxy cache with pinned ARM64 digests.

The web Deployment uses Recreate to serialize startup migrations. Both initial media PVCs were removed by a UID-guarded Fleet cleanup after all pods released them. The completed cleanup Job and its temporary RBAC are retired.

Configuration inherits [shared Training defaults](../../README.md). Edit `instance.yaml` for instructor overrides, then run `python3 scripts/render-training-netbox.py` from the repository root. Generated `values.yaml` and `helmop.yaml` must pass the drift check.
