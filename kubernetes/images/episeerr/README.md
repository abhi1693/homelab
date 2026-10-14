# Episeerr image

ARM64 Episeerr `3.9.6` application on a digest-pinned Python 3.13 Alpine
runtime, running as UID/GID `1000`. Only `/app` is copied from the pinned
upstream image; its Debian filesystem and Python packages are not inherited.
This removes the upstream Debian packages that blocked the security scan.
Timezone data preserves the deployment's `TZ=Asia/Kolkata` behavior.

`requirements.lock` pins every resolved application dependency. Re-resolve it
when updating upstream requirements, then run the image tests and security scan.
The runtime removes pip and setuptools. A scratch final stage flattens the
filesystem so removed package metadata is absent from lower runtime layers.

The image applies `patch-season-progress.py` to the pinned upstream source.
Jellyfin playback becomes aggregate season progress, and the next complete
season becomes eligible at the configured 25 percent threshold. Selected
episodes are monitored before Sonarr receives a `SeasonSearch` for each
represented season. The patch asserts upstream source targets and runs five
behavior tests during the build, so source drift and finale-only regressions
fail the build.

## Build inputs and release gate

- Application source:
  `docker.io/vansmak/episeerr:3.9.6@sha256:0dc70e3c74d04c3d7a55352e181e13f9fdaa50e32537df7f4905ce18aa372530`
- Python runtime:
  `docker.io/library/python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a`
- Published image: `ghcr.io/abhi1693/home-lab-episeerr:3.9.6-2`

The workflow builds on a native ARM64 runner, runs vulnerability and secret
scanning with HIGH/CRITICAL findings blocking release, and checks authenticated
startup under a read-only filesystem before publishing the final tag. Unfixed
findings are included. The Debian-based `3.9.6-1` candidate was never deployed.

Update source/runtime digests, dependency lock and release suffix together.
After publishing, pin the deployed image digest in both init and application
containers and verify Fleet convergence and live integration behavior.

The workflow uses the existing `GIT_TOKEN` registry credential because the
repository-scoped Actions token cannot access this existing GHCR package.
Workflow build arguments and Dockerfile defaults must match.
