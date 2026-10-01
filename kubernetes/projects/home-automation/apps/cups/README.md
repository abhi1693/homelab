# CUPS USB printing

Fleet runs one CUPS instance for the HP Deskjet 2510 series attached to
`k8s-rpi1` (`192.168.3.243`). The printer was detected as USB ID `03f0:ac11`,
serial `CN31T3HGYM05TX`, on USB topology path `3-2`. Neither the physical USB
port nor the transient bus/device number is part of the queue configuration.

## Connect a client

After Fleet deploys the bundle, add this IPP printer manually:

```text
ipp://printer.home:631/printers/hp-deskjet-2510
```

Open `http://printer.home` for CUPS, or `http://printer.home/printers/` for queue status.
Use IPP on macOS/Linux or a Windows Internet Printer connection with the
equivalent `http://printer.home:631/printers/hp-deskjet-2510` URL.
Client compatibility and physical output must be checked after deployment.
The server renders jobs with the image's HP hpcups Deskjet 2510 driver;
the USB printer itself does not need driverless IPP support. Default paper is A4.

Clients on the management LAN (`192.168.1.0/24`), cluster LAN
(`192.168.3.0/24`), and trusted Wi-Fi (`192.168.4.0/24`) can connect. The IoT
network (`192.168.5.0/24`) is excluded. The Service uses the MetalLB
`app-services` pool, source-preserving `externalTrafficPolicy: Local`, and
LAN source restrictions. A NetworkPolicy also restricts ingress to TCP 631
from those subnets and denies egress. There is no Ingress or WAN exposure.

The Service annotation makes ExternalDNS reconcile `printer.home` to
`192.168.3.19` in UniFi DNS. ExternalDNS watches both Ingress and Service
resources. Service ports 80 and 631 both reach CUPS on container port 631.
Wi-Fi clients must use the home DNS resolver (`192.168.3.1`) and have access
to this LAN; isolated guest Wi-Fi is not allowed. Direct IP access at
`http://192.168.3.19:631` remains available for DNS troubleshooting.

Automatic Bonjour/AirPrint discovery is not included. A normal LoadBalancer
does not carry link-local mDNS to the LAN; iPhone/iPad discovery needs a separate
LAN mDNS advertiser and validation. Scanning is also outside this bundle.

CUPS server sharing is enabled with `Browsing Yes` and
`BrowseLocalProtocols dnssd`, as well as `printer-is-shared=true` on the queue.
Disabling server browsing makes the web UI report the queue as `Not Shared`
even when the per-printer shared flag is true. This setting does not provide
LAN mDNS discovery by itself: no host Avahi socket or LAN advertiser is mounted.
HTTP/IPP access logging uses CUPS' special `stderr` destination for container
logs and client setup diagnostics; device-file paths are not used as log files.

For Windows, select **IPP Device** and paste the complete
`ipp://printer.home:631/printers/hp-deskjet-2510` URL, including both slashes.
If installation fails, first open the queue's HTTP URL in the same PC's browser,
then check `kubectl logs -n cups deployment/cups` during another add attempt.
A reachable status page alone does not validate Windows printer installation.

## Web administration

Open **https://printer.home:631/admin/** and sign in as `printadmin`.
Administration requires HTTPS and a password from the same trusted management,
cluster, and Wi-Fi subnets as printing. CUPS uses its persistent self-signed
certificate, so a new browser will show a certificate trust warning. Verify
the hostname and certificate before accepting the local exception.

`secrets.sops.yaml` contains an encrypted `SopsSecret`; the SOPS operator
materializes the `cups-admin` Secret. Startup creates the unprivileged
`printadmin` OS account in `lpadmin` and reads its password from a root-only
Secret mount. The image's default `print/print` account remains locked.
An authorized cluster operator can retrieve the password with:

```sh
kubectl -n cups get secret cups-admin -o jsonpath='{.data.password}' | base64 --decode
```

To rotate the password, use `sops secrets.sops.yaml`, update the encrypted
template's password, then commit and push. Wait for the SOPS operator to
reconcile the new value into the native `cups-admin` Secret before incrementing
the deployment's config-revision annotation in a second Git/Fleet change.
The account password is applied only at container startup; this ordering avoids
starting with the previous Secret value. The username is currently fixed as
`printadmin` in the startup script. Do not commit a decrypted file.

Use the UI for job management and printer operations. Startup reapplies the
Git-owned server policy, USB URI, driver, A4 default, sharing, and default
printer; make durable changes to those settings in Git. A status page remains
available when the USB cable is disconnected and does not prove device readiness.

## Runtime and storage

- Image: `olbat/cupsd:stable`, pinned by digest in `deployment.yaml` and pulled
  through `registry.home`; the selected multi-architecture image includes ARM64
  and the exact Deskjet 2510 hpcups model.
- One replica, `Recreate` updates, and an explicit hostname selector prevent
  concurrent ownership of the printer. There is no automatic hardware failover.
- A retained 1 GiB Longhorn PVC holds configuration, driver PPD, spool, and
  cache under `/var/lib/cups-state`. Completed documents and job history are
  discarded. Pending jobs persist across restarts and may print when the device
  reconnects. CUPS limits jobs to 50 and each request to 100 MiB; the PVC is the
  overall capacity bound.
- Fleet ignores the controller-assigned PVC `spec.volumeName` during drift
  comparison, matching the repository's other persistent apps. The binding
  remains owned by Kubernetes rather than being reset by drift correction.
  This bundle explicitly uses non-forced drift correction, including the local
  target override, so Helm merges changes instead of replacing the bound PVC.
- Startup seeds CUPS defaults only once, reapplies Git-owned server policy and
  the serial-based USB queue, and sets the default printer. After changing the
  ConfigMap, increment `home-lab.io/config-revision` in `deployment.yaml` so
  Fleet replaces the pod. Readiness checks scheduler/queue configuration, not
  whether paper, ink, and the USB device are available.
- LAN clients can print without a password. Web administration uses the
  dedicated `printadmin` account over HTTPS; local root access through the
  CUPS socket remains available. Change durable queue settings in Git.
- USB access requires a privileged root container mounting `/dev/bus/usb`.
  This exposes the node's USB bus, including the UPS currently on `k8s-rpi1`;
  the configured queue targets only the printer serial. No host D-Bus socket,
  host network, or Kubernetes API token is mounted.
- Namespace ownership follows the Fleet namespace runbook, with PSA audit/warn
  labels. The expected restricted-policy warnings reflect the USB exception.

## Move the printer to another Pi

1. Let active print jobs finish, then connect the USB cable to the target Pi.
2. Verify the device using read-only SSH, for example `ssh asaharan@<node-ip> lsusb`.
3. Change only `nodeSelector.kubernetes.io/hostname` in `deployment.yaml` to
   the new node name, then commit/push through the normal Fleet workflow.
4. Wait for the old pod to stop, the Longhorn volume to detach/reattach, and the
   replacement to become ready. Keep the queue URI and Service IP unchanged.

Moving to another USB port on the same Pi needs no Git change. If the old node
is down, Longhorn volume recovery may be required before relocation; follow
the existing node-maintenance runbook instead of force-deleting resources.

## Validate and deploy

```sh
yamllint kubernetes/projects/home-automation/apps/cups
kubeconform -summary -strict \
  kubernetes/projects/home-automation/apps/cups/{namespace,configmap,deployment,pvc,service,networkpolicy}.yaml
python3 scripts/check-kubernetes-resource-bounds.py \
  kubernetes/projects/home-automation/apps/cups/deployment.yaml
python3 scripts/validate-workload-catalog.py
kubectl apply --dry-run=server \
  -f kubernetes/projects/home-automation/apps/cups/namespace.yaml
```

`fleet.yaml` is Fleet configuration and `catalog.yaml` is inventory metadata;
neither is an ordinary Kubernetes resource to apply. Until Fleet creates the
`cups` namespace, server dry runs of namespaced resources fail with
`namespaces "cups" not found`. The namespace dry run does not persist it.

Publish the app and its path in `home-automation-gitrepo.yaml` together through
Git. Fleet first reconciles project registration and then the CUPS bundle.
Do not manually apply the manifests or label nodes. After reconciliation:

```sh
kubectl get bundle -n fleet-local | rg cups
kubectl get bundledeployment -A | rg cups
kubectl get pods,svc,pvc -n cups -o wide
kubectl logs -n cups deployment/cups
dig @192.168.3.1 printer.home +short
curl --fail http://printer.home/printers/
ipptool -t ipp://printer.home:631/printers/hp-deskjet-2510 \
  /usr/share/cups/ipptool/get-printer-attributes.test
```

Check that the BundleDeployment desired/applied deployment IDs match, the
pod is ready on the intended Pi, the PVC is bound, and the Service has
`192.168.3.19`. Query IPP attributes from a LAN client, then send one small test
page and confirm physical output. No physical print is part of local validation.

Rollback configuration by reverting its Git commit. To stop printing while
retaining state, set replicas to zero in Git. The namespace and PVC carry
Helm's keep annotation; removing the Fleet path alone is not a data cleanup.

References: [image source](https://github.com/olbat/dockerfiles/tree/master/cupsd),
[CUPS server configuration](https://openprinting.github.io/cups/doc/man-cupsd.conf.html),
[queue configuration](https://openprinting.github.io/cups/doc/man-lpadmin.html).
