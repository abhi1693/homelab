# Cilium bootstrap and validation

`main` installs Cilium when bootstrapping a new cluster, and configures bundled
Traefik. Once the `fleet-local/cilium` HelmOp exists and targets
`kube-system/cilium`, the role skips Cilium CLI install/upgrade operations;
Fleet then owns runtime changes. The `cli` entrypoint still only maintains the
CLI binary. `validation` inspects network configuration, rollout limits,
readiness, and agent/Hubble metrics on every node.

Both `main` and `validation` use the same kernel compatibility gate. Cilium
versions **1.20.2 and later**, including later patch and minor releases, require
`/sys/kernel/btf/vmlinux` on every cluster node. Missing BTF blocks the role;
there is no compatibility override. Keep the current **1.20.1** pin while the
[upstream regression](https://github.com/cilium/cilium/issues/48778) remains
unresolved for these kernels. Change this boundary only after an upstream fix
and compatibility with the actual host kernels are verified.

The local regression fixtures execute the production Ansible condition and
assertions with synthetic per-node stat results. They use localhost only and
do not run the role, contact cluster hosts, or read live databases. From the
repository root, run:

```sh
python3 -m unittest discover -s infrastructure/ansible/roles/cilium/tests -v
```

The normal Ansible pre-commit hook discovers these role tests automatically.

Keep the rendered `templates/values.yaml.j2` and
[`kubernetes/projects/system/apps/cilium/values.yaml`](../../../../../kubernetes/projects/system/apps/cilium/values.yaml)
equal. Run `scripts/check-cilium-observability.py` from the repository root
after editing Cilium inventory, template, or Fleet values. This prevents a
future bootstrap from silently restoring a different metrics or datapath
configuration.

Hubble exports bounded incident metrics with a 4095-flow cache. Relay and UI
stay disabled. See the [Cilium Fleet README](../../../../../kubernetes/projects/system/apps/cilium/README.md)
for the same-version ownership handoff and rollout procedure. Do not run a
manual Helm or Cilium upgrade after the handoff.
