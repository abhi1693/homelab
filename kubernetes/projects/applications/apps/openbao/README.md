# OpenBao

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

## One-time Shamir migration

The home deployment completed this migration on 2026-07-12. Do not repeat it
against the current static-sealed storage. The procedure remains documented for
restoring a pre-migration Shamir backup or rebuilding the deployment from that
state.

Changing the configuration does not migrate an already initialized Shamir
deployment automatically. Take a storage backup first. After Fleet has deployed
the static-seal Secret and restarted the pod with the new seal configuration,
run:

```bash
kubectl -n wardn exec -ti openbao-0 -- bao operator unseal -migrate
```

Enter the existing Shamir unseal share at the hidden prompt. This deployment has
a `1/1` threshold, so one invocation completes the migration. The old Shamir
share becomes a recovery share. Keep it securely, but do not use it as the
static wrapping key.

Seal migration is a stateful operational change. Reverting only the Helm values
does not revert the stored seal metadata. Migrating back to Shamir requires the
documented reverse seal-migration procedure while the static key is still
available.

## Verification

Verify the migration without exposing either secret:

```bash
kubectl -n wardn exec openbao-0 -- bao status
kubectl -n wardn get pod openbao-0
```

The status should report `Seal Type static`, `Recovery Seal Type shamir`, and
`Sealed false`; the pod should become ready. A subsequent Fleet-managed restart
is the end-to-end check that OpenBao starts unsealed without operator input.

Standalone mode is not highly available. Move this bundle to HA mode with an
external KMS or HSM seal before treating it as production secret storage.
