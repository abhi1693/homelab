# Fleet agent resources

Fleet deploys an initial hook Job and an idempotent ten-minute reconciliation
CronJob. Each local agent explicitly requests 150m CPU and 448Mi memory and
retains its one-core CPU and 1Gi memory limits. Namespace defaults remain a
fallback for other generated containers.

The policy updates only the local provisioning Cluster's Fleet agent resource
customization and the generated Fleet Cluster's agentResources field. Patches
check UID and resourceVersion and preserve scheduling, client identity, secret
references and other customization. Neither Cluster is adopted into a Helm
release or deleted by this bundle. RBAC permits get/patch only on those two
namespaced resources named local.

Two agent replicas and their existing control-plane anti-affinity remain.
The policy pod uses the existing pinned ARM64 Python image, runs non-root with
a read-only filesystem, and never reads application Secrets.

Validate with Python unittest discovery in this directory, Kustomize rendering
and server-side dry runs. Verify both new Fleet agent replicas are Ready with
150m requests and that bundle desired/applied deployment IDs agree.
