# OpenBao

The ARM64 StatefulSet schedules on workers and does not tolerate the
control-plane critical-addons taint.

Minimal OpenBao deployment for the `wardn` namespace.

- Uses the official `openbao/openbao` Helm chart.
- Runs in standalone mode with a 1Gi Longhorn PVC.
- Uses the native `static` seal with key material mounted from the
  `openbao-static-seal` Secret, so OpenBao unseals itself after pod restarts.
- Exposes the UI/API at `http://secrets.wardn.home` through Traefik.

The static seal removes the routine manual-unseal step, but it does not provide
an independent security boundary: the wrapping key and OpenBao run in the same
cluster. The key is stored in Git only as SOPS-encrypted data. Preserve both the
encrypted secret and the age identity needed to decrypt it in backups. Recovery
shares cannot replace a lost static wrapping key; if that key is permanently
lost, the OpenBao data cannot be recovered, including from storage backups.

## Recovery

Restore both the data volume and its matching static wrapping key. A backup
from a different seal configuration requires a separately reviewed seal
migration; changing Helm values alone does not migrate persisted seal metadata.

## Verification

Verify seal status without exposing key material:

```bash
kubectl -n wardn exec openbao-0 -- bao status
kubectl -n wardn get pod openbao-0
```

The status should report `Seal Type static`, `Recovery Seal Type shamir`, and
`Sealed false`; the pod should become ready. A subsequent Fleet-managed restart
is the end-to-end check that OpenBao starts unsealed without operator input.

Standalone mode is not highly available. Move this bundle to HA mode with an
external KMS or HSM seal before treating it as production secret storage.
