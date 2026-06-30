# SOPS Secrets Operator

This bundle installs `isindir/sops-secrets-operator` into the `sops` namespace.
The operator uses the existing `sops/sops-age-key-file` Secret created during
bootstrap. That Secret must contain the same age identity used by local SOPS:

```bash
kubectl -n sops create secret generic sops-age-key-file \
  --from-file=key=/home/asaharan/.config/sops/age/keys.txt
```

Kubernetes SOPS files should use the `.sops.yaml` rule for
`kubernetes/.*\.sops\.ya?ml` and be named like `secrets.sops.yaml`. Use
`SopsSecret` resources rather than encrypted native `Secret` resources; Fleet
applies the encrypted `SopsSecret`, and the operator creates the native
`Secret`.

Example plaintext before encrypting:

```yaml
---
apiVersion: isindir.github.com/v1alpha3
kind: SopsSecret
metadata:
  name: example-app-secrets
  namespace: media
spec:
  suspend: false
  secretTemplates:
    - name: example-app-secrets
      type: Opaque
      stringData:
        API_TOKEN: replace-me
```

Encrypt before committing:

```bash
sops --encrypt --in-place kubernetes/projects/<project>/apps/<app>/secrets.sops.yaml
```

Add the encrypted file to the app `kustomization.yaml`. Fleet applies the
encrypted `SopsSecret`; the operator creates the native Kubernetes `Secret`.
