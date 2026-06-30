# Repository Guidelines

## Project Structure & Module Organization

- `infrastructure/ansible/` owns cluster bootstrap and host configuration. Playbooks are in `playbooks/`, roles in `roles/<name>/`, and the home inventory in `inventories/home/`.
- `kubernetes/` is the post-bootstrap desired state reconciled by Rancher Fleet. Project-scoped apps live in `kubernetes/projects/<project-slug>/apps/<app>/`, project metadata lives in `kubernetes/projects/<project-slug>/_project/`, Fleet control-plane bundles live in `kubernetes/fleet/<app>/`, and legacy app bundles still live in `kubernetes/apps/<app>/` while they are being migrated.
- `coder/templates/python-3-12/` contains the Coder Terraform template for ARM64 Python 3.12 Kubernetes workspaces.
- `infrastructure/network/unifi/` contains manual UniFi BGP configuration and operational notes.

## Build, Test, and Development Commands

- No package manager is used at the repo root.
- `cd infrastructure/ansible && ansible-galaxy collection install -r collections/requirements.yml` installs required Ansible collections.
- `cd infrastructure/ansible && ansible-playbook --syntax-check playbooks/site.yml` checks playbook syntax using `ansible.cfg`.
- `cd infrastructure/ansible && ansible-playbook playbooks/<role>.yml -e <role>_entrypoint=validation` runs a role validation entrypoint, such as `k3s_server_entrypoint=validation`.
- `terraform -chdir=coder/templates/python-3-12 fmt -check` checks Terraform formatting; run `terraform -chdir=... validate` after provider init.
- `coder templates push python-3-12 -d coder/templates/python-3-12` publishes the workspace template.

## Coding Style & Naming Conventions

- YAML uses two-space indentation, `---` document starts, and lower-case kebab-case resource and app names.
- Ansible variables are role-scoped, for example `k3s_server.*` or `fleet_apps_entrypoint`.
- Role task entrypoints are `main`, `validation`, and `reset`; keep new roles consistent with that pattern.
- Kubernetes app directories use service-oriented names such as `media-sonarr` and colocate app-specific README files, values, PVCs, services, and deployments. Project-scoped paths use Rancher project slugs such as `applications` and `entertainment`.
- Keep Terraform formatted with `terraform fmt`.

## Testing Guidelines

- This repo uses validation tasks rather than unit tests. Add or update `roles/<role>/tasks/validation.yml` when role behavior changes.
- For Kubernetes manifests, prefer server-side dry runs when a cluster context is available: `kubectl apply --dry-run=server -f kubernetes/projects/<project>/apps/<app>/` or `kubectl apply --dry-run=server -f kubernetes/apps/<app>/` for legacy bundles.
- For Fleet apps, validate `fleet.yaml` together with referenced values and manifests.

## Cluster Change Policy

- Do not make manual mutating changes to the live cluster. All intended cluster
  state changes must be represented in Git and reconciled by Rancher Fleet.
- AI agents must not run mutating cluster commands such as `kubectl apply`,
  `kubectl delete`, `kubectl patch`, `kubectl label`, `kubectl annotate`,
  `kubectl edit`, `kubectl scale`, `kubectl rollout restart`, `helm install`,
  `helm upgrade`, or `helm uninstall` unless the user explicitly authorizes a
  break-glass operation in that specific turn.
- Read-only cluster inspection is allowed for diagnosis, for example
  `kubectl get`, `kubectl describe`, `kubectl logs`, `helm list`, and
  server-side dry runs.
- If cleanup or repair requires changing live resources, encode it as a
  Fleet-managed manifest, Helm value change, or documented operator action for
  the user to run, rather than changing the cluster directly.
- Namespace manifests and Pod Security Admission labels are especially
  sensitive because incorrect Fleet ownership metadata can make Fleet report a
  namespace as missing or not owned. Follow
  `docs/runbooks/fleet-namespace-psa-labels.md` before adding, removing, or
  relabeling namespaces.

## Commit & Pull Request Guidelines

- Commit history uses concise imperative subjects: `Add ...`, `Fix ...`, `Move ...`, `Replace ...`. Keep subjects scoped and around 72 characters or less.
- Pull requests should describe the affected subsystem, list validation commands run, call out secrets or cluster-impacting changes, and link issues when relevant.
- AI-generated commits should include a `Co-Authored-By:` trailer with the agent identity.

## Security & Configuration Tips

- Never commit plaintext secrets. Files matching `infrastructure/ansible/inventories/home/(group_vars|host_vars)/*.sops.yml` must stay encrypted by SOPS/age per `.sops.yaml`.
- Do not revert unrelated local changes; this repository may contain active infrastructure work.
