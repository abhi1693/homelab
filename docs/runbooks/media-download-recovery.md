# Media download recovery

Use this when requested TV or movies never reach qBittorrent. Diagnose each
stage separately: requests, Sonarr/Radarr monitoring and delay queues, Prowlarr
search, download handoff, and Smart Queues scheduling. Application settings
are retained on PVCs; repair them through the owning application's API or UI.
Deployment, network, and Secret changes must go through Git and Fleet.

## Prowlarr authentication

Repeated `401 Unauthorized` responses from Prowlarr can disable every indexer
in Sonarr and Radarr even while all pods are healthy. Check both directions:
Prowlarr's application connections authenticate to Sonarr/Radarr, and the
synced Torznab indexers authenticate to Prowlarr.

1. Confirm the active service keys with authenticated `system/status` requests.
   Prowlarr's `PROWLARR__AUTH__APIKEY` environment override can differ from its
   retained `config.xml`; use the active Secret-backed key.
2. In Prowlarr Settings -> Apps, repair the Sonarr and Radarr application
   credentials while preserving their URLs, categories, and full-sync policy.
3. Force a full application/indexer sync. The API equivalent is
   `POST /api/v1/command` with
   `{"name":"ApplicationIndexerSync","forceSync":true}`. Inspect completion
   and downstream validation errors; a completed command alone is insufficient.
4. Verify Sonarr/Radarr health and run a search. Individual sources may still
   fail with rate limits, missing definitions, or empty categories; distinguish
   these from a shared authentication failure. Preserve configured sources
   unless their removal is separately intended.
5. Search available, monitored, missing movies and the selected TV seasons.
   RSS scans discover recent releases and do not replace a backlog search.

API responses can mask key fields as `********`; comparing those strings with
a real key does not prove drift. Never send masked values back as replacement
credentials. Keep keys out of command output, logs, shell history, and Git.
Redact application logs before displaying them because some validation errors
include authenticated Torznab URLs.

## Episeerr holds and deleted tags

The `10519200` minute delay for `episeerr_delay` / `episeerr_select` is an
intentional request hold. Episeerr releases it after choosing the rule-owned
seasons. Do not shorten the delay globally or download every season to bypass it.

1. Compare series tag IDs and Jellyseerr's default Sonarr tags with Sonarr's
   current tag list. A numeric reference without a matching tag is orphaned.
   Remove only confirmed deleted references before creating replacement tags,
   since new tags can reuse an old numeric ID.
2. Run Episeerr's integration bootstrap after correcting orphan references.
   It restores the default/control tags, dedicated delay profile, and webhook
   wiring. Jellyseerr defaults retain valid user tags and discard deleted IDs.
3. Resolve each held series to its intended rule. A valid explicit
   `episeerr_select` request must stay in the selection workflow. For a default
   request whose rule tag was deleted, use the configured default rule after
   checking its monitoring choices and any requested starting season.
4. Assign the rule through the authenticated Episeerr UI or
   `POST /api/rules/assign` with `series_id` and `rule_name`. This preserves
   activity state and restores the rule tag. Reassignment is additive; verify
   that the transient hold is gone and the existing monitored seasons remain
   correct. Do not replay a SeriesAdd webhook for an established series without
   checking its playback state, since that workflow resets monitoring.
5. Search already selected seasons with aired, missing, monitored episodes.
   Preserve unmonitored future seasons, playback gates, and cleanup dry-run
   controls. Check that pending-release dates no longer extend decades ahead.

## Completion evidence

Verify successful search results and a report sent to qBittorrent, then inspect
the client and Smart Queues for metadata acquisition, peers, and increasing
downloaded bytes. Client acceptance alone does not establish that a torrent has
usable peers. Free storage, bandwidth budget, and backup-WAN policy must also
permit downloads. Keep unavailable releases separate from infrastructure or
authentication failures.

The October 9, 2026 recovery repaired both Prowlarr application connections,
forced indexer sync, restored nine held series to `season_binger`, and retained
their monitored seasons. A backlog search covered 57 available, monitored,
missing movies. No media files, Secrets, or live Kubernetes resources were
manually replaced.
