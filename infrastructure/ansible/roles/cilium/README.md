# Cilium bootstrap and validation

`main` installs Cilium when bootstrapping a new cluster, and configures bundled
Traefik. Once the `fleet-local/cilium` HelmOp exists and targets
`kube-system/cilium`, the role skips Cilium CLI install/upgrade operations;
Fleet then owns runtime changes. The `cli` entrypoint still only maintains the
CLI binary. `validation` inspects network configuration, rollout limits,
readiness, and agent/Hubble metrics on every node.

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
