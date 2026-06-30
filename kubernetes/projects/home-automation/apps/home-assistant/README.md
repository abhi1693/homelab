# Home Assistant

Home Assistant is installed through the upstream `pajikos/home-assistant`
Helm chart. Rancher Fleet reconciles this app path from Git, and K3s'
Helm controller installs the chart from the `HelmChart` resource.

The initial endpoint is:

- `http://ha.home`

That hostname needs an internal DNS record or local hosts entry pointing to the
Traefik LoadBalancer IP, `192.168.3.3`.

Current choices:

- chart: `home-assistant`
- chart version: `0.3.67`
- app version: `2026.6.4`
- HACS version: `2.0.5`
- namespace: `home-assistant`
- ingress class: `traefik`
- persistence: Longhorn, `1Gi`, `ReadWriteMany`
- code-server add-on: enabled as a sidecar at `http://code.ha.home`
- `/config` volume group access: `fsGroup: 1000`
- active config PVC: `home-assistant-pvc`
- availability model: singleton Deployment pod with Recreate updates on a
  chart-owned RWX config volume
- startup budget: 10 minutes before liveness restarts Home Assistant
- node failure eviction: 30-second `not-ready`/`unreachable` NoExecute
  tolerations

The previous StatefulSet PVC was `home-assistant-home-assistant-0`. Migration to
RWX is done by copying its data to a temporary migration PVC, deleting the old
claim, allowing the chart to create `home-assistant-pvc`, and copying the data
back. Home Assistant still runs as one active instance to avoid duplicate
automation execution. Deployment updates use the `Recreate` strategy because
Home Assistant refuses to start while another instance is running against the
same `/config` directory.
The startup probe gives Home Assistant enough time for config checks, package
loading, and recorder migrations before liveness enforcement begins.
The shorter NoExecute tolerations make Kubernetes evict and replace the pod much
sooner than the default five-minute node-failure grace period.

HACS is bootstrapped by the `install-hacs` init container in
[helmchart.yaml](/home/asaharan/PycharmProjects/home-lab/kubernetes/projects/home-automation/apps/home-assistant/helmchart.yaml).
The init container only installs HACS when `/config/custom_components/hacs` is
missing, so HACS UI-managed updates are not overwritten on normal pod restarts.
If the Home Assistant PVC is kept, HACS survives reinstall and pod recreation. If
the PVC is deleted or rebuilt, the init container installs the pinned HACS
version again before Home Assistant starts.

Hardware mounts remain disabled until there is a concrete device workflow to
expose.

## Code Server

The chart's code-server add-on runs as a sidecar against the Home Assistant
`/config` volume and is exposed through Traefik at:

- `http://code.ha.home`

The chart default runs code-server with `--auth none`, so keep this hostname
limited to the trusted internal network.

The pod sets `fsGroup: 1000` so the code-server container can write to the
shared `/config` PVC.

## UniFi AP PoE schedule

Use the built-in UniFi Network integration for switch-port PoE control. The
automation is managed from Git as a Home Assistant package in
[packages-configmap.yaml](/home/asaharan/PycharmProjects/home-lab/kubernetes/projects/home-automation/apps/home-assistant/packages-configmap.yaml).

1. In UniFi OS, create a local-only admin with Network full management access.
   Cloud/SSO users do not work for Home Assistant's UniFi Network integration.
2. In Home Assistant, add `UniFi Network` from
   `Settings > Devices & services > Add integration`.
3. Open the `USL24PB` UniFi switch device in Home Assistant and enable the
   disabled PoE port control entity for port 13. Use the PoE port entity, not the
   power-cycle button.
4. Commit and push changes under `kubernetes/projects/home-automation/apps/home-assistant/`. Fleet applies
   the ConfigMap and the Home Assistant StatefulSet mounts it at
   `/config/packages`.

Home Assistant packages are enabled by `configuration.templateConfig`, and the
init container also enforces `homeassistant.packages: !include_dir_named
packages` in the persisted `/config/configuration.yaml`.

## Person tracking

The `Abhimanyu Saharan` person is managed from Git in
[packages-configmap.yaml](/home/asaharan/PycharmProjects/home-lab/kubernetes/projects/home-automation/apps/home-assistant/packages-configmap.yaml)
with these device trackers:

- `device_tracker.abhi_pc`
- `device_tracker.abhimanyu_pixel_8`

Home Assistant login users are stored in HA's auth storage, not in package YAML.
Create or update the login user `asaharan` from `Settings > People > Users`, then
link it to the `Abhimanyu Saharan` person in the People UI. If you want that user
link in Git later, copy the Home Assistant user `ID` from the Users tab and add
it as `user_id` on the `person` entry.

The package uses `switch.usw_24_poe_port_13_poe`; confirm the exact entity ID
from the port 13 entity settings in Home Assistant.

The `button.usw_24_poe_port_13_power_cycle` entity only restarts port 13
briefly. It cannot keep the AP powered off from midnight until 05:00.
The `sensor.usw_24_poe_port_13_poe_power` entity only reports current PoE power
draw. It confirms Home Assistant can see the port, but it cannot control power.

Time triggers do not run retroactively. If the automation is created after
midnight, the off action waits until the next midnight. To test immediately, run
`switch.turn_off` against `switch.usw_24_poe_port_13_poe` from Home Assistant's
Actions developer tool, then run `switch.turn_on` to restore power.

Home Assistant is not opted into Stakater Reloader. Package changes are applied
by Fleet, but the Home Assistant pod is restarted intentionally instead of by
automatic config reload automation.

Do not schedule the only AP that provides access to Home Assistant or UniFi
unless both services remain reachable over wired networking while Wi-Fi is off.

## RPi thermal cooling

RPi thermal shutdown decisions are not owned by Home Assistant. The guarded
Prometheus/Kubernetes cooling workflow and node shutdown helpers live with the
qBittorrent smart queues app in
[media-qbittorrent](/home/asaharan/PycharmProjects/home-lab/kubernetes/projects/entertainment/apps/media-qbittorrent/README.md).

Home Assistant only provides local webhook actuators for UniFi PoE control after
smart queues has already persisted its cooling lock and requested clean node
shutdown. The UniFi Network integration maps the RPi nodes to these PoE control
entities:

- `k8s-rpi1`: `switch.usw_24_poe_port_2_poe`
- `k8s-rpi2`: `switch.usw_24_poe_port_4_poe`
- `k8s-rpi3`: `switch.usw_24_poe_port_6_poe`
