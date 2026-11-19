# Training

Instructor and student NetBox labs share the official upstream chart, application version, resources, worker settings, housekeeping, registry proxy, and ephemeral media defaults. Each instance retains a separate namespace, database, credentials, and Valkey task/cache indexes.

## Configuration

- `_shared/netbox/values.yaml` is the common chart configuration.
- `studentPlugins: true` in an instance selects the pinned student web and worker image from `_shared/netbox/student-plugins/values.yaml`. It includes NetBox DNS and NetBox Branching with per-instance database routing.
- `_shared/netbox/chart.yaml` pins the official chart and Helm timeout.
- `apps/<instance>-netbox/instance.yaml` contains only instance differences and optional overrides.
- `values.yaml` and `helmop.yaml` inside each app are rendered Fleet inputs, committed to Git. Do not edit generated files directly.

Run from the repository root (Python 3 with PyYAML):

```sh
python3 scripts/render-training-netbox.py
python3 scripts/render-training-netbox.py --check
```

Mappings merge recursively. Scalars, lists and explicit nulls replace the inherited value. For example, a student can override `values.resources.requests.cpu` without repeating memory or limits. `chart.version` may be overridden per instance for a deliberate upgrade trial; omit it to inherit the common version. Overrides do not mutate shared defaults or another instance. The pre-commit and workload-catalog CI drift checks require all rendered instances to match their sources. Canonical chart updates require a reviewed PR with the renderer output committed alongside the source pin.

## Student ingress and DNS

Student 1 is live. Students 2–5 retain their configured hostnames with ingress disabled and zero web and worker replicas.

| Student | Hostname |
| --- | --- |
| 1 | `netbox-lab1.practicelab.dev` |
| 2 | `netbox-lab2.practicelab.dev` |
| 3 | `netbox-lab3.practicelab.dev` |
| 4 | `netbox-lab4.practicelab.dev` |
| 5 | `netbox-lab5.practicelab.dev` |

Set each public hostname in `allowedHosts`, HTTPS `csrf.trustedOrigins`, and the ingress host. The student ingress class is `cloudflare-tunnel`. The instructor remains at `instructor.netbox.home`. Fleet registers each enabled student in the training GitRepo. Cloudflare Tunnel publishes its hostname and terminates public TLS.

## Add a student

1. Copy an existing student app and its prerequisite directory using a new instance name. Keep `instance.yaml`; replace generated outputs by running the renderer after editing it.
2. Set the instance fullname, app/admin secret references, hostname, trusted origin, dedicated PostgreSQL database/user, and unused Valkey task/cache indexes in `instance.yaml`. Share registry pull credentials, not application credentials.
3. Update the app wrapper identities: Fleet bundle and dependencies, HelmOp name/release/default namespace/labels, values ConfigMap generator and references, Cloudflare connector egress and database/cache NetworkPolicy namespace and pod selectors, and workload catalog. Shared chart settings are regenerated; wrapper identities remain explicit.
4. Create the new namespace/project association and SOPS-encrypted secrets in its prerequisite bundle following `docs/runbooks/fleet-namespace-psa-labels.md`. Add the dedicated role/database through the existing PostgreSQL bundle. Reserve and document two unused Valkey indexes within the configured logical database count; the instructor uses 12/13 and students 1–5 use consecutive pairs from 14/15 through 22/23. Never reuse the instructor database, app secrets or cache indexes.
5. Update the workload catalog and exclusions, run the renderer and repository checks, and review the rendered upstream chart before pushing. Register both new app paths in `kubernetes/fleet/fleet-project-gitrepos/training-gitrepo.yaml`; its paths are explicit. `_shared` is not a deployable bundle.

This setup shares configuration and the existing HA backing services; adding a student still requires an individual capacity and isolation review.

Renovate tracks the canonical shared dependency pins and ignores generated instance inputs. Dependency PRs must regenerate and commit every instance before the drift check passes.

## Housekeeping

Shared defaults disable the obsolete external housekeeping CronJob. NetBox 4.7 no longer provides that management command; each instance's existing RQ worker executes the built-in daily System Housekeeping job. Keep workers enabled and verify completed and scheduled system jobs after upgrades.

The renderer projects complete nonsecret chart settings into each HelmOp's tracked values, and projects maintenance flags from the main NetBox instance's independently maintained values. The `--check` hook rejects projection drift; runtime credentials continue to use existing Secrets.
