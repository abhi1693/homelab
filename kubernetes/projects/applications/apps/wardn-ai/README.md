# Wardn AI

Wardn AI runs its API and frontend in the `wardn` namespace. Runtime records
remain in the shared PostgreSQL service; file-oriented MCP installations and
supporting data are mounted at `/app/data` from the `wardn-ai-data-nfs` PVC.

The custom API and frontend Deployments retain two ReplicaSet revisions; Git
and Fleet history remain the primary rollback path.

Fleet automatic drift correction is disabled for this bundle. The
`local-disable-drift` target customization keeps the local BundleDeployment
opted out even though the parent `home-lab-applications` GitRepo keeps drift
correction enabled for the rest of the project. Git remains the source of
desired state, but Fleet will not automatically revert Wardn AI live resource
drift.

The API and its migration init container each request `50m` CPU, while the
frontend requests `30m`. CPU limits preserve the API's burst ceiling and leave
the frontend uncapped.

Kubernetes MCP runtime pods keep Wardn AI's default `256Mi` memory request but
raise the memory limit to `2Gi` through `WARDN_MCP_RUNTIME_KUBERNETES_MEMORY_LIMIT`.
The higher limit gives package-backed MCP servers room for first-run dependency
resolution without changing per-server manifests.

Hub MCP tool proposal writes use `WARDN_MCP_TOOL_PROPOSAL_API_TOKEN` from the
`wardn-ai` SOPS secret. Keep it empty to disable proactive proposal submission,
or set it to a Wardn Hub token with the required submission scope. Roll the API
Deployment after changing this secret so new pods receive the updated value.

NFS CSI provisions that claim below the retained NAS directory
`wardn/wardn-ai-data-nfs`. The volume uses normal executable mounts so installed
tools, symlinks, and non-root UID/GID `1000` data remain usable by the API and
its init container. Keep the retained directory group-owned by GID `1000` and
let the containers' explicit `runAsGroup: 1000` provide write access; do not set
pod-level `fsGroup` on this large RWX NFS tree because kubelet will recursively
check or change tens of thousands of files during rollouts.

The API and worker mount an explicit projected Kubernetes service-account
volume for the runtime provider while keeping automatic token mounting disabled.
Keep that projected volume world-readable (`0444`) so non-root UID/GID `1000`
can read the token, namespace, and CA bundle without adding pod-level `fsGroup`.
