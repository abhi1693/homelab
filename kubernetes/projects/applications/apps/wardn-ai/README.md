# Wardn AI

Wardn AI runs its API and frontend in the `wardn` namespace. Runtime records
remain in the shared PostgreSQL service; file-oriented MCP installations and
supporting data are mounted at `/app/data` from the `wardn-ai-data-nfs` PVC.

The custom API and frontend Deployments retain two ReplicaSet revisions; Git
and Fleet history remain the primary rollback path.

The API and its migration init container each request `50m` CPU, while the
frontend requests `30m`. CPU limits preserve the API's burst ceiling and leave
the frontend uncapped.

NFS CSI provisions that claim below the retained NAS directory
`wardn/wardn-ai-data-nfs`. The volume uses normal executable mounts so installed
tools, symlinks, and non-root UID/GID `1000` data remain usable by the API and
its init container.
