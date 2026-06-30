---
# Fleet Image

ARM64 Rancher Fleet controller image patched for the local Harbor registry.

The upstream Fleet ImageScan code uses HTTPS for registry references by
default. This cluster intentionally exposes Harbor at `http://registry.home`
and configures K3s containerd to use that HTTP endpoint. Without the patch,
ImageScan tries `https://registry.home/v2/` and stalls on Traefik's default
certificate instead of scanning Harbor.

## Build Inputs

- Fleet source: `rancher/fleet` tag `v0.15.3`
- Patch: `patches/001-registry-home-insecure-imagescan.patch`
- Published image tag family: `ghcr.io/abhi1693/home-lab/fleet*`

## Patch Contract

The patch makes Fleet ImageScan treat `registry.home` image references as an
insecure registry for tag and digest lookups. It also defaults digest lookups
for `registry.home` to `linux/arm64`, matching this cluster's node
architecture. Set `IMAGESCAN_PLATFORM` in the Fleet chart values if another
platform is needed later.

Remove this image and return Rancher to `rancher/fleet` when upstream Fleet has
a first-class ImageScan option for HTTP or insecure registries.
