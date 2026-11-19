# Instructor NetBox

Official community chart 8.3.101 runs NetBox 4.7.4 on ARM64 at https://instructor.netbox.home in the Training project. One web and one worker use shared HA PostgreSQL and Valkey. The retained database is `netbox_instructor`; task/cache DB indexes 12/13 are reserved for this lab. Media is ephemeral (`emptyDir`); no media PVC is required.

Credentials are SOPS-managed in instructor-prerequisites. Retrieve the bootstrap password from Secret `instructor-netbox-admin`, key `password`, through an authorized local Kubernetes client. The namespace is owned by instructor-prerequisites.

All runtime, init, waiter and chart-test images pull through the `registry.home` proxy cache with pinned ARM64 digests.

The web Deployment uses Recreate to serialize startup migrations. Both initial media PVCs were removed by a UID-guarded Fleet cleanup after all pods released them. The completed cleanup Job and its temporary RBAC are retired.

Configuration inherits [shared Training defaults](../../README.md). Edit `instance.yaml` for instructor overrides, then run `python3 scripts/render-training-netbox.py` from the repository root. Generated `values.yaml` and `helmop.yaml` must pass the drift check. The instance explicitly pins chart 8.3.101 to retain the deployed release while the shared default is newer; remove or update that override only as part of a separately reviewed chart upgrade.

## Housekeeping

NetBox 4.7 removed the `manage.py housekeeping` command. Keep the chart's legacy housekeeping CronJob disabled. The existing RQ worker runs NetBox's built-in daily **System Housekeeping** job, including the configured session, changelog and job retention tasks. Verify its completed and next scheduled entries in NetBox's job history and check that the worker remains Ready. Do not replace it with ad hoc cleanup or change retention settings to resolve a CronJob alert.

The renderer also projects complete nonsecret chart values into inline HelmOp values. This ensures a maintenance-policy change participates in Fleet's deployment identity instead of relying only on a copied ConfigMap. Both forms derive from the same canonical shared/instance configuration.

The worker explicitly imports `core.jobs` before invoking NetBox's native `rqworker` command. The deployed 4.7.4 app configuration otherwise registers only the search-cache safety-net job at startup. This bootstrap restores native daily housekeeping registration and schedule recovery without changing retention, installing code at runtime, or using the removed management command.
