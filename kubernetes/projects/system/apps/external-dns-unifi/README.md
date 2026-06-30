# ExternalDNS for UniFi

ExternalDNS watches Kubernetes Ingress hosts and reconciles matching records into
UniFi DNS through the `kashalls/external-dns-unifi-webhook` provider.

Current choices:

- chart: `external-dns`
- chart version: `1.21.1`
- external-dns version: `0.21.0`
- Fleet/Helm release name: `external-dns-unifi`
- workload name: `external-dns-unifi`
- UniFi webhook image:
  `registry.home/ghcr.io/kashalls/external-dns-unifi-webhook:v0.8.2`
- namespace: `kube-public`
- source: `ingress`
- ingress class: `traefik`
- trigger loop on Kubernetes events: `true`
- periodic reconciliation interval: `30m`
- domain filter: `home`
- policy: `sync`
- DNS ownership registry: TXT records with owner ID `home-lab`

This app expects a Secret named `external-dns-unifi` in the
`kube-public` namespace:

The UniFi webhook image is pulled through the public `ghcr.io` Harbor proxy
cache project, so it does not need an image pull Secret.

```bash
kubectl -n kube-public create secret generic external-dns-unifi \
  --from-literal=api-key='<unifi-api-key>'
```

Do not commit the UniFi API key to Git. The Fleet bundle can be pushed after the
Secret exists.

ExternalDNS reads hosts from `Ingress.spec.rules[].host`. With the current
Traefik ingress, `ha.home` is reconciled to the ingress load balancer
address `192.168.3.3`.

Because `policy` is `sync`, ExternalDNS may delete records it owns when matching
Ingress hosts are removed. The `home` domain filter and TXT ownership records
keep the scope limited to this cluster's managed records.
