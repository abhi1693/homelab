# Episeerr image

ARM64 Episeerr `4.0.5` application on a digest-pinned Python 3.15 Alpine
runtime, running as UID/GID `1000`. Only `/app` is copied from the pinned
upstream image; its Debian filesystem and Python packages are not inherited.
Timezone data preserves the deployment's `TZ=Asia/Kolkata` behavior.

`requirements.lock` pins every resolved application dependency. Re-resolve it
when updating upstream requirements, then run the image tests and security scan.
The lock includes `certifi==2026.10.19`, fixing GHSA-6q48-6c7w-9gw2.
The runtime removes pip and setuptools. A scratch final stage flattens the
filesystem so removed package metadata is absent from lower runtime layers.

The image applies `patch-season-progress.py` to the pinned upstream source.
Jellyfin playback becomes aggregate season progress, and the next complete
season becomes eligible at the configured 25 percent threshold. Selected
episodes are monitored before Sonarr receives search commands. Fully missing
seasons use `SeasonSearch`; partial seasons use `EpisodeSearch` for missing
files only. The upstream protection against searching files already on disk
is retained, including repeated playback events. The patch asserts upstream source targets and runs
behavior tests during the build, so source drift and finale-only regressions
fail the build.

## Build inputs and release gate

- Application source:
  `docker.io/vansmak/episeerr:4.0.5@sha256:fdba03bb48468048a4aef4ba34f202518bf8dd7b55c24578cbbe12fcf61fac74`
- Python runtime:
  `docker.io/library/python:3.15-alpine@sha256:ff4d3c9b1a48f646eedd93182aaea385c7a5452f4c8a8cd7cef686babacf4928`
- Published image: `ghcr.io/abhi1693/home-lab-episeerr:4.0.5-1`

The workflow builds on a native ARM64 runner, runs vulnerability and secret
scanning with HIGH/CRITICAL findings blocking release, and checks authenticated
startup under a read-only filesystem, the exact app version, anonymous API
rejection and authenticated API access before publishing the final tag. Unfixed
findings are included.

Update source/runtime digests, dependency lock and release suffix together.
After publishing, pin the deployed image digest in both init and application
containers and verify Fleet convergence and live integration behavior.

The workflow uses the existing `GIT_TOKEN` registry credential because the
repository-scoped Actions token cannot access this existing GHCR package.
Workflow build arguments and Dockerfile defaults must match.

The image and Fleet bootstrap retain upstream 4.x worker recycling at 2,000
requests plus up to 200 requests of jitter. Gunicorn's control socket is
disabled because the application root filesystem is read-only.
