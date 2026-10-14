# SonarQube MCP Server

Fleet deploys Sonar's official ARM64 MCP server into the existing `devfeed`
namespace. The endpoint is `https://sonar.mcp.home/mcp`, accessible over the LAN
or VPN. Traefik terminates TLS with a certificate from `home-local-ca`;
clients must trust that CA. ExternalDNS creates the internal DNS record.

The image is pinned to `1.19.0.2785` and its ARM64 digest, pulled through Harbor.
The server uses Streamable HTTP on port 8080, SonarCloud organization `abhi1693`,
and default project `abhi1693_devfeed.tech`. Read-only mode is enforced at server
level. Enabled toolsets are issues, rules, sources, quality-gates, measures,
coverage, duplications, and security-hotspots.

## Client authentication

The server stores no Sonar token. Each client must send its own SonarCloud user
token in `Authorization: Bearer <token>` on every request. Since the organization
is fixed at startup, clients must not send a `SONARQUBE_ORG` header.

For a Codex client, configure the remote endpoint in its user-level
`~/.codex/config.toml` (outside the repository):

```toml
[mcp_servers.sonarqube]
url = "https://sonar.mcp.home/mcp"
startup_timeout_sec = 120

[mcp_servers.sonarqube.http_headers]
Authorization = "Bearer <SONARCLOUD_USER_TOKEN>"
```

Replace the placeholder locally and restrict the configuration file to mode
`0600`. Never commit or display the populated header. Start a new Codex session
to load the configuration. Clients must trust the home-lab CA.

The server has no Kubernetes API credentials. Network policy permits ingress
from Traefik and egress to cluster DNS and public HTTPS, excluding private IPv4
ranges. Writable storage uses bounded `emptyDir` volumes and is ephemeral.

## Validation and rollout

```sh
kubectl kustomize kubernetes/projects/applications/apps/sonarqube-mcp-server
kubectl apply --dry-run=server -k kubernetes/projects/applications/apps/sonarqube-mcp-server
```

Publish through Git and wait for Fleet reconciliation. Check the bundle's
desired/applied deployment IDs, pod readiness and restarts, certificate readiness,
DNS, `/health`, and `/info`. Verify an unauthenticated MCP request is rejected,
then test authenticated initialization and tool listing with the user token.

Rollback by reverting the application registration and manifests in Git and
letting Fleet reconcile. No namespace is created or relabeled by this app.

Upstream: https://github.com/SonarSource/sonarqube-mcp-server/tree/1.19.0.2785
