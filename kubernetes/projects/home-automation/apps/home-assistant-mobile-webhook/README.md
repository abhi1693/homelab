# Home Assistant Mobile Webhook Gateway

This deployment gives the Home Assistant Companion App a narrow, self-hosted
path for sending sensor and location updates while a phone is away from the
home network. Cloudflare Tunnel publishes
`https://sensors.abhimanyu-saharan.com/api/webhook/<capability>` without exposing
the Home Assistant UI, REST API, WebSocket API, or authentication endpoints.

The reusable gateway source, tests, container workflow, security model, and
operator-neutral deployment examples live in
[`abhi1693/ha-sensors-gateway`](https://github.com/abhi1693/ha-sensors-gateway).
This GitOps bundle owns only the household-specific ingress, encrypted webhook
capabilities, network boundaries, and deployment of the released image.

The encrypted SOPS configuration authorizes separate webhook capabilities for
the Pixel 8, Pixel 10 Pro, and iPhone. Requests must use the exact 64-character
mobile-app webhook ID assigned to that device and one of these native commands:
`get_config`, `get_zones`, `register_sensor`, `update_location`, or
`update_sensor_states`. Commands that can call services, fire events, render
templates, process conversations, stream cameras, scan tags, or change mobile
registration and push destinations are returned as an indistinguishable `404`
and are never sent to Home Assistant.

The gateway does not filter sensor names or attributes: every sensor included in
an authenticated Companion App batch is forwarded unchanged. It additionally
enforces JSON-only requests, a 2 MiB batch limit, strict path validation,
duplicate-key rejection, a per-capability rate limit, a fixed upstream, bounded
responses, secret-free logs, a non-root read-only container, and NetworkPolicies
that permit only Cloudflare connector ingress and Home Assistant egress. The
deployment pins the multi-architecture `0.2.1` image by tag and OCI index
digest, and its startup, readiness, and liveness probes require a successful
`GET /healthz` response from a request handler.

## Companion App setup

On the Pixel 8, Pixel 10 Pro, and iPhone, keep `http://ha.home` as the Companion
App internal URL and configure `https://sensors.abhimanyu-saharan.com` as the
external URL. The external host deliberately cannot open the Home Assistant
interface; it exists only for background sensor delivery.

## Validation

```sh
kubectl kustomize .
kubectl apply --dry-run=server -k .
```

Gateway unit, lint, formatting, and container tests run in the source
repository's CI workflow for every source change.

## Upgrades

Source PRs and release publication both require native AMD64 and ARM64 image
builds, SBOMs, strict HIGH/CRITICAL vulnerability and secret scans, and isolated
runtime HTTP tests. The smoke checks source/image version parity, the exact
Python version, non-root identity, pip absence, health probes and forwarding of
one permitted read command. Blocked controls and unknown capabilities must not
reach its loopback-only test upstream.

Verify the immutable release digest, exact source revision, provenance and shared
workflow attestation before updating this Deployment. Renovate tracks published
images within the `0.2.x` series, including digest pins. After Fleet's desired
and applied IDs match, verify readiness, zero restarts and the live Python/app
version. Check `/healthz` and an unknown path from inside the pod, requiring
`200` and `404` respectively. Preserve the existing public non-webhook denial
responses at the Cloudflare boundary. Exercise real
device capabilities only through normal Companion App traffic. Keep the Home
Assistant image, ingress boundaries and encrypted capability configuration
unchanged during a gateway-only update.
