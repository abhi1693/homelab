# Home Lab

Infrastructure, Kubernetes desired state, custom images, and Coder workspace
templates for a Raspberry Pi ARM64 home lab.

The repository is organized around two control planes:

- Ansible bootstraps hosts and the base K3s cluster.
- Rancher Fleet reconciles the post-bootstrap Kubernetes state from Git.

Live cluster changes should normally be made in this repository and reconciled
by Fleet. Read-only inspection is fine for diagnosis, but mutating `kubectl`,
`helm`, or similar commands should be treated as break-glass operations.

## Repository Map

| Path | Purpose |
| --- | --- |
| `infrastructure/ansible/` | Host preparation, K3s bootstrap, Cilium, kube-vip, cert-manager, Rancher, Longhorn, and Fleet bootstrap roles. |
| `infrastructure/network/unifi/` | Manual UniFi BGP configuration and operational notes for service VIP advertisement. |
| `kubernetes/` | Fleet-managed Kubernetes desired state after bootstrap. |
| `kubernetes/projects/<project>/` | Rancher project metadata and project-scoped app bundles. |
| `kubernetes/fleet/` | Fleet control-plane bundles. |
| `kubernetes/images/` | Repo-owned application image Dockerfiles and image documentation. |
| `coder/templates/` | Self-contained Coder Terraform templates for ARM64 Kubernetes workspaces. |
| `docs/` | Architecture decisions and runbooks. |

## Operating Model

Bootstrap work starts in `infrastructure/ansible`. The site playbook applies
the roles in dependency order, validating each major phase after it is
configured:

```sh
cd infrastructure/ansible
ansible-galaxy collection install -r collections/requirements.yml
ansible-playbook --syntax-check playbooks/site.yml
```

Individual roles can be validated through their validation entrypoint:

```sh
cd infrastructure/ansible
ansible-playbook playbooks/k3s_server.yml -e k3s_server_entrypoint=validation
```

After bootstrap, day-to-day application changes live under `kubernetes/` and
are reconciled by Rancher Fleet. For an app change, edit the owning bundle,
commit and push to the configured Fleet branch, then let Fleet converge the
cluster.

## Kubernetes Projects

Project-scoped apps live in `kubernetes/projects/<project>/apps/<app>/`.
Project metadata lives in `kubernetes/projects/<project>/_project/` and is
tracked separately because Rancher `Project` resources contain immutable fields.

| Project | Path | Owns |
| --- | --- | --- |
| Applications | `kubernetes/projects/applications/` | Public app workloads such as the blog, Postal, ShipyardHQ, and Tree Pop. |
| Database | `kubernetes/projects/database/` | CloudNativePG, shared PostgreSQL, PgBouncer poolers, Valkey, and database network boundaries. |
| Development | `kubernetes/projects/development/` | Coder and development chart repository registration. |
| Entertainment | `kubernetes/projects/entertainment/` | Media stack storage, chart repositories, and media workloads. |
| Home Automation | `kubernetes/projects/home-automation/` | Home Assistant, NetBox, and Cloudflare Tunnel ingress controller. |
| System | `kubernetes/projects/system/` | Cluster system add-ons such as ExternalDNS and Rancher Backup. |

For Kubernetes validation, prefer server-side dry runs when a cluster context is
available:

```sh
kubectl apply --dry-run=server -f kubernetes/projects/<project>/apps/<app>/
```

## Coder Templates

`coder/templates/` contains self-contained Terraform templates because
`coder templates push -d <template-dir>` uploads only the selected directory.
Available templates include Node.js, Python, NetBox plugin development, and
Ubuntu desktop workspaces.

Shared template scripts are maintained under `coder/templates/_shared/` and
vendored into each template:

```sh
coder/templates/sync-shared.sh
coder/templates/check-shared.sh
```

Validate a template after provider initialization:

```sh
terraform -chdir=coder/templates/python-3-12 fmt -check
terraform -chdir=coder/templates/python-3-12 validate
```

Publish templates with:

```sh
coder templates push python-3-12 -d coder/templates/python-3-12
```

See `coder/templates/README.md` for the full catalog and push flow.

## Custom Images

Repo-owned images live in `kubernetes/images/` and are built by GitHub Actions
for `linux/arm64`.

| Image area | Path | Notes |
| --- | --- | --- |
| Jellyfin | `kubernetes/images/jellyfin/` | Custom Jellyfin image work for PostgreSQL-backed horizontal scaling experiments. |
| NetBox | `kubernetes/images/netbox/` | NetBox image customization and plugin requirements. |
| Postal | `kubernetes/images/postal/` | Postal image customization. |
| Coder workspaces | `coder/templates/base/image/` | Shared base layers for Coder workspace templates. |

## Secrets

Do not commit plaintext secrets. Inventory secrets under
`infrastructure/ansible/inventories/home/(group_vars|host_vars)/*.sops.yml`
must remain encrypted with SOPS and age according to `.sops.yaml`.

Some runtime secrets are intentionally outside Git, such as database backup
credentials and application credentials that Fleet should not own. Document
required manual secrets in the relevant app README or runbook.

## Documentation

| Document | Purpose |
| --- | --- |
| `kubernetes/README.md` | Kubernetes and Fleet operating model. |
| `coder/templates/README.md` | Coder template catalog, image flow, validation, and push commands. |
| `infrastructure/network/unifi/README.md` | UniFi BGP assumptions and router-side configuration. |
| `docs/architecture/adr-001-jellyfin-horizontal-scaling.md` | Jellyfin horizontal scaling architecture decision. |
| `docs/runbooks/fleet-namespace-psa-labels.md` | Sensitive Fleet namespace ownership and PSA label rollout procedure. |
| `docs/runbooks/jellyfin-sqlite-to-postgresql-migration.md` | Jellyfin SQLite-to-PostgreSQL migration rehearsal notes. |

## Contribution Notes

- Use two-space YAML indentation and `---` document starts.
- Keep Kubernetes resource, app, and directory names lower-case kebab-case.
- Keep Ansible variables role-scoped, such as `k3s_server.*` or
  `fleet_apps_entrypoint`.
- Keep role task entrypoints consistent: `main`, `validation`, and `reset`.
- Keep Terraform formatted with `terraform fmt`.
- Do not revert unrelated local changes; this repository may contain active
  infrastructure work.
