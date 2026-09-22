# NetBox MCP Server

The NetBox MCP Server exposes authenticated, per-user NetBox CRUD operations to
MCP clients without storing a shared NetBox token. It runs in the `netbox`
namespace and reaches NetBox through its internal-LAN ingress hostname.

## Endpoint

- MCP URL: `https://mcp.netbox.home/mcp`
- Browser guide: `https://mcp.netbox.home/`
- NetBox target header: `X-NetBox-URL: https://netbox.home/`
- Authentication: `Authorization: Bearer <NetBox v2 token>`

The local `home-local-ca` ClusterIssuer provides the ingress certificate. MCP
clients must trust the Home Lab Local CA. Traefik is the only permitted ingress
source and terminates TLS before forwarding traffic to the pod.

## Runtime

- image: `registry.home/home/netbox-mcp-server:0.0.3`
- image digest: `sha256:cb8b1a4c453fb241cd5415c837da0764d6d50540faeb32f3258dd5076bce12f5`
- architecture: ARM64
- namespace: `netbox`
- replicas: `1`
- process identity: UID/GID `1000`
- root filesystem: read-only, with a bounded `/tmp` volume
- Kubernetes API credentials: not mounted

The server allows only `https://netbox.home/` as a downstream NetBox target.
NetworkPolicy permits only DNS and HTTPS egress through Traefik. Generic plugin
POST actions are enabled, but every invocation requires a write-enabled token,
the applicable NetBox permission, and `confirm=true`. Core API paths remain
unavailable through the action tool. Administrative model writes are enabled
for reviewed schema maintenance, but still require the applicable per-user
NetBox permission. Non-expiring tokens are explicitly accepted for the current
operator credential; delete confirmation remains required.

For the manual UniFi infrastructure inventory workflow, use the
[UniFi to NetBox drift runbook](../../../../../docs/runbooks/networking/unifi-netbox-drift-reconciliation.md).
It keeps UniFi access read-only, excludes all Network client data, and applies
only reviewed infrastructure writes through this MCP server.

For K3s inventory and IPAM, use the
[K3s-to-NetBox drift runbook](../../../../../docs/runbooks/k3s-netbox-drift-reconciliation.md).
It keeps Git, live Kubernetes, physical identity, and NetBox authority separate
and excludes ephemeral Pods, workload IPs, and ClusterIPs.

## Health probes

Startup, readiness and liveness use native HTTP GET probes on /, with
Host: netbox-mcp-server for the host allowlist and Accept: text/html for
the browser guide. This avoids starting a Python process on every probe.
The three-second timeout and failure thresholds are unchanged. Verify fresh
probe events and restart counts after Fleet rolls out the change; rollback
is a Git revert of the probe change.

## Validation

Render and validate the bundle before rollout:

```sh
kubectl kustomize kubernetes/projects/home-automation/apps/netbox-mcp-server
kubectl apply --dry-run=server \
  -f <(kubectl kustomize kubernetes/projects/home-automation/apps/netbox-mcp-server)
```

After Fleet reconciles, verify the deployment and endpoint:

```sh
kubectl -n netbox rollout status deployment/netbox-mcp-server
kubectl -n netbox get certificate netbox-mcp-server-home
curl --cacert /path/to/home-local-ca.crt https://mcp.netbox.home/
```
