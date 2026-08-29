# Home Assistant go2rtc relay

This app supplies Home Assistant with a dedicated go2rtc WebRTC relay. It
replaces the embedded relay whose ICE host candidate used an unroutable
Kubernetes pod address for browsers on the home Wi-Fi networks.

## Network paths

| Path | Purpose | Boundary |
| --- | --- | --- |
| Home Assistant to `home-assistant-go2rtc:1984/TCP` | Authenticated signaling and dynamic stream registration | Cluster-only Service and pod-selector NetworkPolicy |
| LAN clients to `192.168.3.17:8555/TCP,UDP` | WebRTC media | MetalLB VIP, limited to `192.168.0.0/16` |
| go2rtc to `192.168.1.1:7441/TCP` | Protect RTSPS sources advertised by the UDM Pro | Exact NVR address and port only |
| go2rtc to `192.168.1.174:7441/TCP` | Master Bedroom Protect RTSPS source advertised by Protect Storage | Exact NVR address and port only |

The go2rtc API is not exposed through the LoadBalancer or an Ingress. Its
credentials are generated randomly, encrypted in the Home Assistant
`SopsSecret`, injected into Home Assistant as environment variables, and used
by an init container to render the private go2rtc configuration file. The
relay omits go2rtc's generic `exec` and general configuration API surfaces.
The ffmpeg module remains enabled because Home Assistant registers an Opus
audio-transcode source alongside each Protect RTSPS stream; only the
authenticated cluster-internal stream API can add it. The relay can update its
memory-backed config volume because go2rtc persists every dynamic stream
registration there; the container root filesystem stays read-only and the
registrations are discarded on pod replacement.

The relay bundle depends only on MetalLB. Home Assistant has an authenticated
startup gate that waits up to five minutes for the relay API, so a fresh cluster
or simultaneous bundle update cannot leave camera entities stuck on HLS merely
because Home Assistant won the startup race.

The relay advertises only IPv4 TCP/UDP candidates at the fixed
`192.168.3.17:8555` endpoint. Stream sources are registered dynamically by Home
Assistant and are not stored in Git.

## Validation

```sh
kubectl apply --dry-run=server -f deployment.yaml -f service.yaml -f networkpolicy.yaml
kubectl -n home-assistant get deploy,pod,svc,networkpolicy -l app.kubernetes.io/name=home-assistant-go2rtc
kubectl -n home-assistant logs deployment/home-assistant-go2rtc
```

From a LAN client, verify TCP reachability to `192.168.3.17:8555`, then use an
authenticated Home Assistant WebRTC offer to measure ICE connection and first
video-frame time. The API port `1984` must remain unreachable from the LAN.
