# Repository Guidelines

## Skill Discovery

For every substantive task in this repo, search Wardn Hub for applicable skills
using the `find-skills` skill before proceeding. If an applicable Wardn Hub skill
is found, use it according to the `find-skills` workflow.

If `find-skills` is not installed, install it first:

```sh
npx -y @wardn-ai/skills install 'abhi1693/wardn-hub/find-skills' --global --agent codex
```

## Project Structure & Module Organization

- `infrastructure/ansible/` owns cluster bootstrap and host configuration. Playbooks are in `playbooks/`, roles in `roles/<name>/`, and the home inventory in `inventories/home/`.
- `kubernetes/` is the post-bootstrap desired state reconciled by Rancher Fleet. Project-scoped apps live in `kubernetes/projects/<project-slug>/apps/<app>/`, project metadata lives in `kubernetes/projects/<project-slug>/_project/`, and Fleet control-plane bundles live in `kubernetes/fleet/<app>/`.
- `coder/templates/` contains ARM64 Coder Terraform templates for Node.js 22/24/26, NetBox plugin development, Python 3.12, and Ubuntu Desktop Kubernetes workspaces.
- `infrastructure/network/unifi/` contains UniFi LAN integration and operational notes.

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

## Documentation & README Maintenance

- Keep README files in sync with every change. When modifying a subsystem,
  update the closest README next to that subsystem and the root `README.md` when
  the change affects the repository overview, architecture, bootstrap flow,
  validation commands, public dependency list, hardware summary, or operational
  workflow.
- The root `README.md` contains static badge values. When changing pinned
  versions or capacity facts, update the matching badge and any prose/table
  entry in the same change. Important sources include K3s in
  `infrastructure/ansible/inventories/home/group_vars/all.yml`, Cilium and
  Rancher in `infrastructure/ansible/inventories/home/group_vars/k3s_servers.yml`,
  Longhorn in `infrastructure/ansible/inventories/home/group_vars/k3s_nodes.yml`,
  and Renovate in
  `kubernetes/projects/applications/apps/renovate/cronjob.yaml`.
- Run `scripts/sync-readme-versions.py --check` after changing any of those
  pinned versions. Use `scripts/sync-readme-versions.py --update` to refresh the
  root README's static version badges and K3s/Cilium overview rows.
- Do not add badges that depend on private repository, cluster, monitoring, or
  runtime endpoints. Public clones must render without access to private GitHub
  Actions status, Prometheus, Grafana, Rancher, or cluster APIs.
- If a version, image tag, chart version, node count, CPU/memory/storage fact,
  external dependency, or validation command changes, search for stale mentions
  across README files before finishing.

## Testing Guidelines

- This repo uses validation tasks rather than unit tests. Add or update `roles/<role>/tasks/validation.yml` when role behavior changes.
- For Kubernetes manifests, prefer server-side dry runs when a cluster context is available: `kubectl apply --dry-run=server -f kubernetes/projects/<project>/apps/<app>/`.
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
