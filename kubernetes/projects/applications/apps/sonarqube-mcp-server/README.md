# SonarQube MCP Server

Fleet deploys Sonar's official ARM64 MCP server into the existing `devfeed`
namespace. The endpoint is `https://sonar.mcp.home/mcp`, accessible over the LAN
or VPN. Traefik terminates TLS with a certificate from `home-local-ca`;
clients must trust that CA. ExternalDNS creates the internal DNS record.

The image is pinned to `1.31.0.4891` and its multi-platform OCI digest, pulled through Harbor.
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

Upstream: https://github.com/SonarSource/sonarqube-mcp-server/tree/1.31.0.4891

## Resource sizing

See [deployment.yaml](deployment.yaml), [kustomization.yaml](kustomization.yaml) for the configured resources and [the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review) for the historical measurements.

## November security qualification

The official ARM64 candidate passed native Java 21.0.13 / Node 24.22.1 checks,
default JVM and Node trust-store checks for the inventory's distrusted CA
fingerprints, and isolated non-root read-only HTTP/authentication checks.
See the [qualification workflow source](../../../../images/sonarqube-mcp-qualification/README.md).
Trivy 0.76.1 reported zero HIGH/CRITICAL image findings. The shaded JAR removes
Maven package metadata; the upstream Gradle lock and published ARM64 SBOM were
assessed separately. The Gradle handlebars 4.3.1 alert is limited to test
configurations, and its classes are absent from the distributed JAR. No runtime
finding was suppressed. The existing read-only mode and explicit toolsets remain.
