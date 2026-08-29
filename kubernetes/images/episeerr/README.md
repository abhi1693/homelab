# Episeerr Image

ARM64 Episeerr image based on the exact upstream `3.8.9` multi-architecture
digest.

The wrapper upgrades `msgpack`, uses current `setuptools` only while building,
then removes both `pip` and `setuptools` from the runtime. The upstream image
ships `msgpack 1.1.2` and `setuptools 70.3.0`, which have fixable high-severity
findings. A `scratch` final stage flattens the patched filesystem so superseded
package metadata is not retained in lower image layers. The runtime user is
also changed from root to numeric UID/GID `1000`.

The image also applies `patch-season-progress.py` to the pinned upstream source.
Jellyfin playback is converted into aggregate season progress, and the next
complete season becomes eligible at the configured 25 percent threshold. The
selected episodes are monitored before Sonarr receives a `SeasonSearch` for
each represented season, so a current-season remainder cannot hide the next
season from the search command. The
patch asserts every upstream source target and runs `test-season-progress.py`
during the build, so source drift or finale-only regressions fail the image
build.

## Build Inputs

- Base image:
  `docker.io/vansmak/episeerr:3.8.9@sha256:7b14478931249cc3ae3a14f7cc56354f6191dfc498a1079b0b8878c604267be7`
- `msgpack`: `1.2.1`
- Build-only `setuptools`: `84.0.0`
- Published image: `ghcr.io/abhi1693/home-lab-episeerr:3.8.9-5`

The GitHub workflow builds on an ARM64 runner and publishes the fixed release
tag. Update the base digest and release suffix together when Episeerr changes.
