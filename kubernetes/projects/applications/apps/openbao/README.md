# OpenBao

Minimal OpenBao deployment for the `wardn` namespace.

- Uses the official `openbao/openbao` Helm chart.
- Runs in standalone mode with a 1Gi Longhorn PVC.
- Exposes the UI/API at `http://secrets.wardn.home` through Traefik.

Standalone mode is not highly available and still requires the normal OpenBao init/unseal workflow. Move this bundle to HA mode with a real unseal strategy before treating it as production secret storage.
