---
title: Cloudflare Tunnel Ingress Controller
---

# Cloudflare Tunnel Ingress Controller

Fleet installs the `strrl.dev/cloudflare-tunnel-ingress-controller` Helm chart into
the `cloudflare` namespace. Public applications opt in by setting
`spec.ingressClassName: cloudflare-tunnel` on their Kubernetes `Ingress`.

The controller uses the existing Cloudflare tunnel named `production-apps` and
manages DNS records plus tunnel ingress rules for matching Ingress objects.
Cloudflare API credentials are not stored in Git. The chart expects a runtime
Secret in the `cloudflare` namespace:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-api
  namespace: cloudflare
stringData:
  api-token: <cloudflare-api-token>
  cloudflare-account-id: <cloudflare-account-id>
  cloudflare-tunnel-name: production-apps
```

The token must allow `Account.Cloudflare Tunnel:Edit`, `Zone.DNS:Edit`, and
`Zone.Zone:Read`.

Images are pulled through the local Harbor proxy cache:

- `registry.home/cr.strrl.dev/strrl/cloudflare-tunnel-ingress-controller`
- `registry.home/docker.io/cloudflare/cloudflared`

These proxy-cache projects are public in Harbor, so the controller and
controller-managed `cloudflared` connector pods do not need an image pull
Secret.

The chart exposes connector metrics through the controller-managed
`cloudflared` pods on port `44483`. `cloudflaredServiceMonitor.create` is enabled
so Rancher Monitoring scrapes those metrics through a Prometheus Operator
`ServiceMonitor`; the companion NetworkPolicy allows only the Rancher Monitoring
Prometheus pods to reach that metrics port.
