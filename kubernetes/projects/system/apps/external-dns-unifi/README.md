# ExternalDNS for UniFi

ExternalDNS watches Kubernetes Ingress hosts and annotated Services, then
reconciles matching records into UniFi DNS through the
`kashalls/external-dns-unifi-webhook` provider.

Current choices:

- chart: `external-dns`
- chart version: `1.22.0`
- external-dns version: `0.22.0`
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

Validate changes by rendering chart `1.22.0` with `values.yaml`, checking both
`--source=ingress` and `--source=service`, and server-dry-running the rendered
resources. After Fleet reconciliation, verify the controller is ready, check
its reconciliation logs, and query `dig @192.168.3.1 printer.home +short`.
Keep the Service annotation and Service source enabled together: with `sync`,
removing either can remove the managed printer DNS record.
