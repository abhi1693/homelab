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

This app reads the `api-key` field from the `external-dns-unifi-sops` Secret in
the `kube-public` namespace. Rancher Fleet deploys that Secret from the
SOPS-encrypted
`../external-dns-unifi-secrets/secrets.sops.yaml` manifest referenced by this
app's `fleet.yaml`. Do not reuse this credential to collect or import UniFi
Network client data into NetBox; the manual NetBox workflow is
infrastructure-only.

The UniFi webhook image is pulled through the public `ghcr.io` Harbor proxy
cache project, so it does not need an image pull Secret.

Rotate the key only by updating the encrypted `api-key` field with SOPS. Never
commit or print the plaintext key, and do not create a competing Secret by hand
because the SopsSecret controller enforces ownership of the generated Secret.

ExternalDNS reads hosts from `Ingress.spec.rules[].host`. With the current
Traefik ingress, `ha.home` is reconciled to the ingress load balancer
address `192.168.3.3`.

Because `policy` is `sync`, ExternalDNS may delete records it owns when matching
Ingress hosts are removed. The `home` domain filter and TXT ownership records
keep the scope limited to this cluster's managed records.
