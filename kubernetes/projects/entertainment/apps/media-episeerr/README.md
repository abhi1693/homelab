# Episeerr

Fleet-managed season-ahead automation for the standard Sonarr library.

Episeerr is available at `http://episodes.media.home`. Authentication is
enabled, the username is `asaharan`, and the configured password is stored only
in the encrypted `media-episeerr` SopsSecret.

## Download Policy

The seeded `season_binger` rule is the default:

- `always_have: s1` searches the complete requested starting season for a new
  series;
- `get_type: seasons` with `get_count: 1` keeps the complete current season
  available and searches the next complete season when aggregate playback
  reaches 25 percent of the current season;
- `keep_type: all` never removes downloaded episodes;
- global and environment cleanup dry-run controls remain enabled as a second
  deletion guard.

Jellyseerr's default, non-4K Sonarr server is bootstrapped with
`episeerr_default` and `episeerr_delay`. A dedicated Sonarr delay profile holds
the request before Sonarr can grab every monitored season. Jellyseerr's
otherwise-unused singleton webhook sends manually and automatically approved
requests to Episeerr so the requested starting season is retained. Episeerr
then receives the Sonarr series-add event, changes monitoring to the rule-owned
season, and removes the transient delay tag. Bootstrap refuses to overwrite a
different Jellyseerr webhook destination.

Fleet rollout does not automatically bulk-migrate existing Sonarr series.
Assign one through the Episeerr UI, or add both `episeerr_default` and
`episeerr_delay` before triggering the Episeerr Sonarr webhook. A one-time
queue migration may instead add the resolved rule tag without firing a search.
For managed series, set Sonarr's new-item policy to `none` and leave seasons
beyond the playback gate unmonitored so RSS cannot grab them first.

## Playback Automation

The custom Jellyfin image includes the official Webhook plugin `21.0.0.0`.
Fleet seeds a generic destination for episode `PlaybackStart` and
`PlaybackStop` events. Episeerr polls Jellyfin every 60 seconds after playback
starts and combines the current episode position with its playback percentage.
For the `asaharan` user, it advances the season rule as soon as aggregate
season progress reaches 25 percent. Jellyfin episode events are fail-closed to
the standard TV media root (`/media/tv`); Anime library items are ignored. The
next season is not searched again once all of its episodes are already monitored.
When the threshold is crossed, Episeerr first monitors the exact selected
episodes and then sends Sonarr a `SeasonSearch` for every distinct selected
season, including the complete next season.

The retained 50 percent episode setting is only a compatibility sampling
fallback if Jellyfin-to-Sonarr season-position resolution is unavailable. The
next-season decision still uses the separate 25 percent aggregate-season gate.

## Runtime Shape

- Image: `registry.home/ghcr.io/abhi1693/home-lab-episeerr:3.8.9-5`
- Upstream release: `vansmak/episeerr:3.8.9`, pinned by digest in the image
  Dockerfile
- Service: `episeerr.media.svc.cluster.local:5002`
- Config and SQLite state: retained 1Gi Longhorn PVC
- Ephemeral logs, activity payloads, and temp files: bounded `emptyDir` volumes
- Pod user: UID/GID `1000`, read-only root filesystem, dropped capabilities,
  RuntimeDefault seccomp, and no service-account token

The image workflow must publish `3.8.9-5` before Fleet can start the workload.
The wrapper upgrades the two upstream Python packages that had fixable
high-severity scan results and applies an assertion-guarded season-progress
patch with behavioral tests during the image build.

## Network Boundary

The separate `media-episeerr-networkpolicy` bundle allows:

- ingress from Traefik, Sonarr, Jellyfin, and Jellyseerr on TCP `5002`;
- egress to Sonarr `8989`, Jellyfin `8096`, Jellyseerr `5055`, DNS, and public
  HTTPS outside cluster pod/service CIDRs.

The matching caller and callee policies are declared in the Sonarr, Jellyfin,
and Jellyseerr bundles.

## Credentials

The SopsSecret stores the generated UI password, Flask session key, and the
Jellyseerr API key copied from the current service. Sonarr and Jellyfin API keys
are referenced from the existing `media-jellyfin-arr-api-keys` Secret and are
not duplicated.

After reconciliation, retrieve the UI password when needed:

```sh
kubectl -n media get secret media-episeerr \
  -o go-template='{{index .data "AUTH_PASSWORD" | base64decode}}{{"\n"}}'
```

## Validation

```sh
kubectl apply --dry-run=server \
  -f kubernetes/projects/entertainment/apps/media-episeerr/
kubectl apply --dry-run=server \
  -f kubernetes/projects/entertainment/apps/media-episeerr-networkpolicy/
```

After Fleet reconciles, verify the image is available, the config-seeding init
container completed, the startup log reports `Episeerr integrations configured`,
the Jellyfin Webhook plugin is active, and a test request carries both transient
Episeerr tags before using the policy for existing series.
