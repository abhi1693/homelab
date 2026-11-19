# kube-vip control-plane VIP

The pinned `v1.3.1` manager advertises the K3s registration VIP `192.168.3.2`
on `eth0` in ARP mode. It manages only the control plane (`svc_enable=false`);
MetalLB owns application Service VIPs. Each manager uses its node-local K3s
API at `127.0.0.1:6443` for leader election.

Version 1.3.1 corrects the binary version stamp in the 1.3.0 release. The
upstream shared-Service-VIP restriction does not apply to this control-plane-only
deployment. The annotated lease lock uses Get/Create/Update operations covered
by the existing role. Keep the VIP, interface, service mode, lease timings,
node-local API and resource bounds intact when changing the version.

Before applying, verify all nodes Ready, all three etcd endpoints healthy and
attached Longhorn volumes healthy. Render/check the role and verify the ARM64
image. The DaemonSet uses RollingUpdate with at most one unavailable manager;
monitor authenticated `/readyz` calls through the VIP throughout the rollout and
record the lease holder before and after its handoff.

Run from `infrastructure/ansible` on the bootstrap server target:

```sh
ansible-playbook playbooks/kube_vip.yml --check --diff
ansible-playbook playbooks/kube_vip.yml
ansible-playbook playbooks/kube_vip.yml -e kube_vip_entrypoint=validation
```

The main entrypoint writes the tracked RBAC and DaemonSet manifests into the
K3s manifests directory on server-1. Validation first waits for the live image
to match the pin, avoiding acceptance of the old completed rollout while K3s
has not yet reconciled the file. It then checks every control-plane manager,
node-local API wiring, resource bounds and authenticated API readiness through
the VIP. Prove all three replacement managers Ready and inspect restart counts
and lease ownership before proceeding to another platform change.
