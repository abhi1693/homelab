# UPS Monitoring

This bundle runs Network UPS Tools for the APC Back-UPS Pro 1500 connected by
USB to `k8s-rpi1`, with PeaNUT as the web dashboard.

The internal endpoint is:

- `http://ups.home`

That hostname needs an internal DNS record or local hosts entry pointing to the
Traefik LoadBalancer IP, `192.168.3.3`.

Current choices:

- namespace: `ups`
- NUT image: `instantlinux/nut-upsd:2.8.3-r4`
- dashboard image: `brandawg93/peanut:6.0.0`
- Prometheus exporter image: `druggeri/nut_exporter:3.3.0`
- ingress class: `traefik`
- hostname: `ups.home`
- NUT service endpoint: `ups-monitoring.ups.svc.cluster.local:3493`
- PeaNUT metrics endpoint: `ups-monitoring.ups.svc.cluster.local/api/v1/metrics`
- NUT exporter metrics endpoint: `ups-monitoring.ups.svc.cluster.local:9199/ups_metrics?ups=ups`
- USB node: `k8s-rpi1`
- USB driver: `usbhid-ups`
- UPS serial: `0B2428G26638`

The NUT container is pinned to `k8s-rpi1`, mounts host `/dev/bus/usb`, and runs
privileged because the NUT USB HID driver needs direct access to the UPS device.
The deployment uses a `Recreate` update strategy so only one pod tries to own
the USB device at a time.
The init container also supplies a minimal `upsmon.conf` with
`SHUTDOWNCMD "/bin/true"` so a low-battery event does not try to power off a
host from inside the privileged container. Cluster shutdown automation should be
added separately as Git-managed desired state if needed.

PeaNUT reads `/config/settings.yml`, seeded from the `ups-monitoring` ConfigMap
in [configmap.yaml](/home/asaharan/PycharmProjects/home-lab/kubernetes/projects/home-automation/apps/ups-monitoring/configmap.yaml).
The active `/config` directory is an `emptyDir`, so dashboard-side UI edits do
not become durable desired state. Change the ConfigMap in Git instead.

The NUT API password is generated into a pod-local in-memory `emptyDir` during
init and is not stored in Git. PeaNUT is configured for read-only UPS status
without NUT credentials. If you later want PeaNUT to issue NUT write commands,
replace the generated runtime secret with a Git-safe secret workflow and add the
matching `USERNAME` and `PASSWORD` fields to `settings.yml`.

PeaNUT authentication is disabled with `AUTH_DISABLED=true` because this
dashboard is internal-only and the app has no durable auth volume or Git-safe
credential source. If external exposure is added later, switch this to a
persistent auth configuration before exposing the route.

Home Assistant can add the `Network UPS Tools` integration with:

- host: `ups-monitoring.ups.svc.cluster.local`
- port: `3493`
- UPS name: `ups`

The network policy allows Traefik to reach the dashboard, Home Assistant to
reach NUT, Rancher Monitoring to scrape UPS metrics, and LAN clients to reach
the pod ports for local diagnostics.

Rancher Monitoring scrapes PeaNUT and the NUT exporter every 60 seconds through
the `ServiceMonitor` in this bundle. The PeaNUT scrape provides the detailed
NUT numeric variables, while the NUT exporter provides status flags that are
easier to alert on. Grafana auto-loads the `UPS / NUT` dashboard from the
`cattle-dashboards` ConfigMap and alerts are defined in `prometheusrule.yaml`.
