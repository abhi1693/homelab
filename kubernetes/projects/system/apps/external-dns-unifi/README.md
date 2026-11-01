# ExternalDNS for UniFi

ExternalDNS watches Kubernetes Ingress hosts and annotated Services, then
reconciles matching records into UniFi DNS through the
`kashalls/external-dns-unifi-webhook` provider.

Current choices:

- chart: `external-dns`
- chart and controller version: declared by the pinned chart in `fleet.yaml`
- Fleet/Helm release name: `external-dns-unifi`
- workload name: `external-dns-unifi`
- UniFi webhook image:
  `registry.home/ghcr.io/kashalls/external-dns-unifi-webhook:v0.9.0`
- namespace: `kube-public`
- sources: `ingress`, `service`
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
Ingress hosts or Service hostname annotations are removed. The `home` domain filter and TXT ownership records
keep the scope limited to this cluster's managed records.

LoadBalancer Services opt in with the `external-dns.kubernetes.io/hostname`
annotation. ExternalDNS uses the allocated Service IP as the DNS target. For
example, the CUPS Service owns `printer.home`, pointing directly to
`192.168.3.19` for HTTP and IPP. Services without a hostname annotation do not
create records; no FQDN template is configured. The Traefik ingress-class
filter continues to apply to the Ingress source.

Validate changes by rendering the pinned chart with `values.yaml`, checking both
`--source=ingress` and `--source=service`, and server-dry-running the rendered
resources. After Fleet reconciliation, verify the controller is ready, check
its reconciliation logs, and query `dig @192.168.3.1 printer.home +short`.
Keep the Service annotation and Service source enabled together: with `sync`,
removing either can remove the managed printer DNS record.

The UniFi API key is SOPS-encrypted under the companion SopsSecret template's
`stringData.api-key`; `data` requires base64-encoded input. Keep the encrypted
template and generated Secret consistent when rotating credentials.

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `kube-public/external-dns-unifi/external-dns` | 10m → 10m | 32Mi → 80Mi | 96Mi → 128Mi |
