# Cilium bootstrap and validation

`main` installs Cilium when bootstrapping a new cluster, and configures bundled
Traefik. Once the `fleet-local/cilium` HelmOp exists and targets
`kube-system/cilium`, the role skips Cilium CLI install/upgrade operations;
Fleet then owns runtime changes. The `cli` entrypoint still only maintains the
CLI binary. `validation` inspects network configuration, rollout limits,
readiness, and agent/Hubble metrics on every node. Runtime validation uses
`k3s kubectl` and the `cilium-dbg` binary inside each running agent. It requires
one non-terminating Ready agent per cluster node and a healthy agent response;
it does not require a host Cilium CLI or the old on-disk Traefik bootstrap
manifest. The CLI version is checked by the `cli` entrypoint. Traefik is checked
through its deployed HelmChartConfig, workload, ingress and Service resources.

Both `main` and `validation` use the same kernel compatibility gate. Cilium
versions **1.20.2 and later**, including later patch and minor releases, require
`/sys/kernel/btf/vmlinux` on every cluster node. Missing BTF blocks the role;
there is no compatibility override. The **1.20.4** pin is qualified against
the nine Ubuntu BTF-enabled kernels and the recorded preflight checks. Keep
BTF-less hosts on 1.20.1 while the
[upstream regression](https://github.com/cilium/cilium/issues/48778) remains
unresolved; do not bypass the gate for future patch or minor upgrades.

The local regression fixtures execute production Ansible conditions and
assertions with synthetic BTF and Pod data. Runtime cases cover missing or
duplicate agents, unready Pods, ignored terminating Pods and unhealthy agents
inside otherwise Ready Pods. They use localhost only and
do not run the role, contact cluster hosts, or read live databases. From the
repository root, run:

```sh
python3 -m unittest discover -s infrastructure/ansible/roles/cilium/tests -v
```

The normal Ansible pre-commit hook discovers these role tests automatically.

Keep the rendered `templates/values.yaml.j2` and
[`kubernetes/projects/system/apps/cilium/values.yaml`](../../../../kubernetes/projects/system/apps/cilium/values.yaml)
equal. Run `scripts/check-cilium-observability.py` from the repository root
after editing Cilium inventory, template, or Fleet values. This prevents a
future bootstrap from silently restoring a different metrics or datapath
configuration.

Hubble exports bounded incident metrics with a 4095-flow cache. Relay and UI
stay disabled. See the [Cilium Fleet README](../../../../kubernetes/projects/system/apps/cilium/README.md)
for runtime ownership and rollout checks. Do not run a manual Helm or Cilium
upgrade alongside Fleet.
