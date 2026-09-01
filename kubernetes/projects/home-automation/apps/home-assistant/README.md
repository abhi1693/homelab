# Home Assistant

Home Assistant is installed through the upstream `pajikos/home-assistant` Helm
chart. Rancher Fleet reconciles this directory and K3s' Helm controller installs
the resulting `HelmChart` resource.

- endpoint: `http://ha.home`
- chart version: `0.3.75`
- app version: `2026.8.3`
- namespace: `home-assistant`
- replicas: `1`, using `Recreate` updates
- persistence: Longhorn `4Gi` RWX PVC `home-assistant-pvc`
- Recorder: dedicated `home_assistant` PostgreSQL database through the
  two-replica `postgresql-pooler-home-assistant-rw` session pool
- code-server: `http://code.ha.home`

Home Assistant remains a singleton because two instances sharing one config
directory can duplicate automations and contend over storage. The startup probe
allows ten minutes for config checks and recorder migrations, while 30-second
node-failure tolerations shorten recovery after a node is lost.

Recorder history, events and long-term statistics are stored in the shared
CloudNativePG cluster. The database has its own bounded role, retained database,
two-replica PgBouncer pool and namespace-scoped NetworkPolicies. Its connection
URL is SOPS-encrypted and injected as `HOME_ASSISTANT_RECORDER_DB_URL`; no
credential is stored in the source repository or rendered documentation.

The first PostgreSQL rollout runs only after the previous singleton pod has
stopped. An idempotent init container copies the SQLite database plus any WAL
and shared-memory sidecars into
`/config/backups/recorder-sqlite-pre-postgresql-20260814`, writes checksums and
then leaves those files untouched. The old database is a rollback archive, not
an imported history source, because Home Assistant does not support migrating
Recorder data between engines.

Rollback is GitOps-only: revert the source pin and Recorder environment change
in this bundle, let Fleet stop the singleton pod, and restart against the
untouched `/config/home-assistant_v2.db`. Keep the timestamped backup and its
`SHA256SUMS` file until PostgreSQL history, statistics, backups and failover have
been verified over a normal retention window. Do not copy a SQLite backup over
the live file while Home Assistant is running.

The archive init container has a temporary 384Mi memory limit because copying
the 225Mi SQLite file charges filesystem cache to its cgroup. Its normal request
remains 32Mi and the container exits before Home Assistant starts.

## Application source

Portable Home Assistant source is owned by the public
[`abhi1693/home-assistant`](https://github.com/abhi1693/home-assistant)
repository. This deployment pins commit
`44589ba9200c1c7bc87c8cb444bd19001194fcef` and the SHA-256 of its GitHub source
archive. The `install-home-assistant-source` init container verifies the archive
before running its standard-library-only bootstrap against `/config`.

The source repository owns:

- `configuration.yaml`, YAML dashboards, local themes and future packages
- the startup guard that unregisters the built-in `/home/overview` panel
- the HACS, dashboard assets and custom-integration versions and checksums
- guarded area assignments plus a declarative seven-room registry that places
  fans, cameras, appliances and paired speaker integrations through Home
  Assistant's area and label APIs
- the canonical Home address, zone coordinates and Google Weather location
- account-specific Pixel 8 and Pixel 10 Pro next-alarm cards on Home
- compact icon-and-percentage battery cards for all three family phones
- private Health views for Abhimanyu, Krishna and Manisha, tailored to each
  phone's available movement, sleep and measurement signals; empty categories
  and explanatory cards stay out of the interface while backend isolation
  remains enforced between accounts
- a compact Home-sidebar leaderboard below Shopping that ranks all three family
  members by their current daily step totals
- shared, direction-gated arrival ETAs for Abhimanyu, Krishna and Manisha plus
  an owner-only Pixel-to-Work ETA that hides at Work; the existing private
  Google API key and Abhimanyu's Work coordinates stay in the Home Assistant
  PVC, while Krishna and Manisha's Work coordinates are supplied by the
  SOPS-encrypted `home-assistant-private-locations` Secret; source bootstrap
  owns Proximity, named Work zones, routing and refresh policy
- dual-home Proximity and traffic-aware routes for Home and Manzil Apartment
- personalized daylight Work routes on weekdays for Abhimanyu and Manisha and
  Monday through Saturday for Krishna
- viewer-aware concurrent Jellyfin session cards without additional API polling
- event-driven Music Assistant cards for dynamic browser players that are not
  exposed as native Home Assistant media-player entities
- read-only LG ThinQ washer status in Guest Room and guarded Bosch Home Connect
  dishwasher status and controls in Kitchen
- backend-enforced shared and owner-only Google Calendar access
- an account-filtered Protect event feed with automatic activity focus,
  per-camera filtering, an optional single-day filter, a default newest-to-oldest
  31-day timeline grouped under date headings, fast server pagination and
  automatic infinite scrolling, recovery backfills
  after Protect reloads or
  event-WebSocket reconnects, a 24-hour startup history seed, bounded
  thumbnails and private byte-range clips with forward/backward seeking,
  presence-aware alerts, and a backend-authorized Master Bedroom camera speaker;
  grants cover each camera's complete Protect device while NVR and console
  entities remain administrator-only
- an admin-only Seerr pending-request queue with approve/decline actions
- the one-time automation reset and legacy storage-dashboard cleanup

This repository owns only Kubernetes/Fleet concerns: chart values, persistence,
ingress, policies, registry credentials and local CA trust. Update the source
commit, archive checksum and `HOME_ASSISTANT_SOURCE_REVISION` together to deploy
a new Home Assistant source revision. The environment value deliberately changes
the pod template and triggers a `Recreate` rollout.

## Dashboards

The family-facing `Home` dashboard contains five bounded views: household
overview, rooms and Atomberg fan controls, Security, People, and private
per-account Health. The household overview always presents the same three-camera
wall—Outside, Living Room, and Kitchen—to every family account; the Security view
retains its broader profile-specific camera access. Music Assistant/Jellyfin
activity remains embedded in the household overview. The dashboard uses the source
repository's `Family Dark` visual system plus pinned Bubble Card, Button Card,
Navbar Card, Card Mod, Kiosk Mode and Auto Entities assets. The design follows
the composition of
[`jlnbln/My-HA-Dashboard`](https://github.com/jlnbln/My-HA-Dashboard): a fixed
left navigation rail, personalized narrative header, adaptive status strip,
dominant camera wall, adaptive media, a source-owned 14-day Coming up
agenda with at most four readable events, adjacent humidity and color-coded
family-wide India NAQI summary cards, and
glanceable area summaries. The
narrative ends with one unlabeled, prioritized household
status for unsafe air, laundry, current events, significant weather, shopping
needs or an all-clear; routine fan-off state is omitted. The header names the
current air-quality category naturally, while the compact summary carries a
plain-language severity, AQI value and matching color. Independent family announcements
sit in the household rail between the agenda and Shopping. The compact bulletin
collapses to its heading and Add action while empty.
The family briefing includes the current day part and time, surfaces today's or
tomorrow's birthday, and changes weather guidance for morning,
afternoon, evening and night.
Outside is the double-width primary camera and Living Room combines both fans.
`/home-tablet/rooms` is a compact shared index; nested paths such as
`/home-tablet/rooms/office` and `/home-tablet/rooms/kitchen` open focused room
details. Every family account can currently view and manage every room. Primary
occupants are context and ordering metadata only: Krishna for Master Bedroom,
Abhimanyu and Manisha for Bedroom, and Abhimanyu for Office. Room details use
senior-friendly circular fan controls. The large
centre shows only On or Off, starts at the retained speed or turns the fan off,
with six direct speed targets around it and an icon-only Boost position. Light
and Sleep remain visible but cannot be changed while the
fan is off. The timer changes between Turn on later and Turn off later, and an
immediate conflicting action cancels it first. Sleep and Timer are mutually
exclusive; selecting one lets the fan replace the other in the same native
command without an extra API call. A fixed centre rotor moves only
while its fan is running, unavailable devices show only a wall-switch message,
and each fan accepts only one pending command at a time. Living Room presents its
two fans as equal tiles inside its room module; every other fan is similarly
contained so appliances, media, cameras and future devices can coexist. A
speed choice while off sends separate power and speed commands matching the
provider API. Favourite rooms are
personalized by account: Abhimanyu sees Office, Bedroom and Living Room;
Krishna sees Master Bedroom, Kitchen, Living Room and Dining Room; Manisha sees
Bedroom, Kitchen, Living Room and Guest Room. The retired browser-review account
is removed during bootstrap. Desktop and phone layouts share the same
source-owned information hierarchy. The source browser suite validates nested
navigation, controls and reflow at 375px, 430px, 844px, 1024px and 1440px widths.

Guest Room includes the electrically-aware LG washer as read-only cycle status.
Kitchen includes the Bosch dishwasher with progress and consumable warnings;
program selection and power are advanced controls, while program start requires
confirmed connectivity, remote-control permission, remote-start permission, a
closed door, a selected program and explicit confirmation. Office and Kitchen
merge each physical Echo's Alexa and Music Assistant entities into one card.
Bedroom and Guest Room TV modules remain hidden placeholders until the real TV
entities are added and their physical mapping is confirmed.

Abhimanyu and Krishna each receive a private sixth status item for the next
alarm reported by their Pixel 8 or Pixel 10 Pro Companion App. It displays
`No alarm` when no usable state is available and remains read-only because
Android cannot reliably target the first existing Clock alarm for replacement.
The household sidebar also shows all three mapped phones in one compact row;
battery fill, charging glyph and semantic color communicate state without
adding status prose.
Abhimanyu alone sees the Google Travel Time Home-to-Work card immediately above
the phones. It formats the integration's traffic-aware state as minutes and
does not copy private route coordinates into Git.

The owner-only household rail also contains a compact Seerr request queue
between Announcements and Shopping. Home Assistant polls the in-cluster service
once per minute and exposes only sanitized title, type and requester data to the
browser. Approve is immediate; decline requires confirmation. Both backend
services independently require an active Home Assistant administrator and
refuse request IDs that are no longer pending.

Every family member sees Home, Rooms, Cameras, Security, People and their own
Health page in the shared rail; admins also see Rack and Settings. Health
sensors are assigned to exactly one profile. Only the three declared daily step
totals are shared across family accounts for the ranked Home leaderboard; every
other health sensor remains denied to other profiles independently of dashboard
visibility. Heart, oxygen, breathing, body and sleep readings remain excluded
from Recorder history. The Home family row combines each person's avatar,
approximate home/away likelihood and color-coded phone battery state; tapping a
person opens Home Assistant's location panel. Internet status appears only when
degraded. A Git-owned
custom integration backs the bulletin's focused Add dialog. Family members can
publish multiple independently expiring messages without opening a raw entity
dialog. Each row identifies its authenticated sender and expiry; only its sender
or an administrator can remove it. Expired content is deleted from persistent
storage and the dashboard, while publication sends a notification to the three
Companion App phones mapped in the family access policy.

Family account mappings, person trackers and camera grants are GitOps-owned in
the source repository. Bootstrap validates immutable user IDs, local login
usernames, tracker entities, Protect entities and Google calendars before
creating or repairing person links and generating Lovelace user filters. For
non-owner profiles it also reconciles a backed-up Home Assistant permission
group that grants only that profile's health entities while denying ungranted
cameras and every calendar except Birthdays; the same group additionally grants
the three explicitly shared daily step totals. Camera policy applies to streams,
smart-detection metadata, event history, recording diagnostics, and speakers
rather than relying on Lovelace visibility alone. The
owner agenda additionally includes Google Family, India holidays, Abhimanyu's
personal calendar and both Topmate calendars. Krishna's Pixel 10 Pro is assigned
to `person.krishna`; Manisha's iPhone is assigned to `person.manisha`. Abhimanyu,
as owner, can access every declared camera. Krishna's permission group grants all
five declared cameras. Manisha's grants cover Kitchen Balcony, Kitchen, Living
Room, and Outside, without the Master Bedroom stream, activity, diagnostics, or
speaker. Outside, Living Room, and Kitchen are the shared Home wall for all three
accounts. The retired non-family
browser-review account, credentials and frontend preferences are removed after
its immutable identity is revalidated; backups make the retirement recoverable.

The owner profile uses the concise Git key `abhimanyu` and visible entity
`person.abhimanyu`. Its existing Home Assistant user UUID, login, phone entities,
Person registry identity and trackers remain unchanged. The completed one-time
rename code is absent from normal startup; its pre-migration entity-registry
backup remains available for recovery.

`Rack` is a separate admin-only dashboard with Kubernetes, UniFi and rack health.
Its incident cards link to filtered workload and Fleet dashboards or directly
to the relevant node, Longhorn, backup, and UPS panels. Scrape-target and alert
cards open Prometheus's filtered native Targets page and Alertmanager's active
alert list instead of a custom Grafana dashboard.
The header power badge reports the UPS source as `Mains`, `Battery`, or
`Transition`; the separate on-battery binary sensor remains the alert signal.
The source bootstrap backs up and removes existing storage-mode custom dashboard
registrations, leaving only these two custom dashboards. A source-owned system
integration unregisters Home Assistant's built-in `/home/overview` panel after
the frontend initializes. Bootstrap also sets `home-tablet` as the system and
family-profile default, so opening `http://ha.home` resolves to
`/home-tablet/home` instead of the removed built-in panel.

Home Assistant is source-pinned to the metric unit system. Every dashboard
temperature card renders an explicit `°C`; package-owned template sensors also
convert the two UniFi rack readings that natively publish Fahrenheit.
The Home pin is G3-012, Indiabulls Centrum Park at
`28.4978819, 76.9830822` with a 100 metre radius. Bootstrap also reconciles the
Google Weather location snapshot to that pin without changing its credentials.

Open the family dashboard directly at:

- `http://ha.home/home-tablet/home`

The room model references only fixed entities verified in the live registry:
all eight Atomberg fans, three Protect cameras, the LG washer, Bosch dishwasher,
Office Echo, Kitchen Echo Dot, weather and presence, Music Assistant, Shopping
List, the authorized Google calendars and Jellyfin active clients.
Auto Entities discovers playing or paused native Music Assistant players,
hidden dynamic Music Assistant browser sessions and Jellyfin sessions without
hard-coding transient client entities. The hidden-player bridge shares the
official integration's WebSocket event stream, so it performs no additional
polling. Active cards identify their source and playback destination. Jellyfin
also supplies the signed-in viewer and client; Music Assistant supplies the
player/device but does not expose the initiating person, so the dashboard does
not infer one. App launchers sit below playback rather than acting like source
column headings. TV playback controls remain future work.

The source also pins the `abhi1693/ha-atomberg-integration` fork. Cloud control
is the default and first choice for every fan. Successful commands update Home
Assistant immediately, then one debounced all-fan cloud read confirms rapid
controls and replaces any optimistic mismatch. Confirmed cloud state also
refreshes the startup cache. State polling runs hourly with a 24-call rolling
allocation, while a persisted hard limit caps all cloud traffic at 1000 calls
per rolling 24 hours and spaces calls below five per second. The quota-tier
migration starts a fresh accounting window, while a new provider denial still
restores the 24-hour breaker. UDP remains the zero-quota fallback for a fan with
current UniFi network
presence. Atomberg's HTTP 403 explicit-deny quota response opens a persisted
24-hour circuit breaker instead of triggering authentication retries. During a
quota outage, HA loads the integration from its persistent device cache, keeps
present fans locally controllable, clears stale pre-migration addresses, and
marks electrically disconnected fans unavailable until LAN presence or an
authoritative cloud refresh returns. Local broadcasts and presence updates do
not postpone the fixed hourly cloud poll. UniFi arrivals restore powered fans,
while departures immediately mark electrically disconnected fans unavailable.

Moon, Uptime, Shopping List and a local `Family` calendar are built-in,
zero-credential integrations configured on the persistent Home Assistant volume.
Their Git-owned cards place moon phase and the shared family board on Home and
the Home Assistant start time on Rack.

Protect cards explicitly request live rendering. Ambient grids prefer the
medium stream and open high resolution on interaction. The source-owned event
bridge consumes Protect's local WebSocket, retains at most 20 events per camera
for seven days in lightweight entity state, and queries completed clips in
account-authorized newest-first server pages. An empty date filter covers the
latest 31 days, while selecting one date queries only that calendar day; the
timeline groups clips under day headings. Thumbnails and clips are exposed only
through account-aware Home Assistant endpoints, while infinite scrolling appends
each page without hiding matches or waiting for the full range to scan. Completed clips are cached privately
within the Home Assistant process and served with arbitrary HTTP byte ranges for
forward and backward seeking. Detection alerts are deduplicated;
life-safety and baby-cry events are immediate, while perimeter smart detections
require high-confidence empty-home state and lower-severity alerts respect quiet
hours. The Master Bedroom camera speaker uses Google Translate TTS and verifies
the caller's camera grant in the backend.

The scoped UniFi policy allows the K8s network to reach TCP `443` (Protect API)
and `7441` (RTSPS) on the UDM Pro at `192.168.1.1` and the Master Bedroom-only
Protect Storage recorder at `192.168.1.174`, plus TCP `7004` on cameras that
expose a Protect speaker. Home Assistant sends authenticated signaling and
dynamic stream registration to the cluster-only `home-assistant-go2rtc` API.
That relay pulls RTSPS from the exact recorder addresses and advertises the
fixed `192.168.3.17:8555` TCP/UDP WebRTC candidate to LAN browsers. Browsers
never need direct Protect, camera, pod-CIDR, or go2rtc API access. Offline cards
recover automatically when Protect reports their cameras connected again.

## Network and media integrations

Reverse-proxy HTTP configuration is UI-owned under `Settings > System > Network`;
there is no deprecated top-level `http:` YAML block.

Home Assistant has narrowly scoped media paths:

- go2rtc signaling: `http://home-assistant-go2rtc.home-assistant.svc.cluster.local:1984/`
- go2rtc WebRTC media: `192.168.3.17:8555/TCP,UDP`
- Music Assistant: `https://music.media.home`
- Jellyfin: `http://jellyfin.media.svc.cluster.local:8096`
- Seerr: `http://jellyseerr.media.svc.cluster.local:10241`

The go2rtc API credentials come from the SOPS-encrypted
`home-assistant-go2rtc` Secret and are never exposed to dashboard browsers. A
credential rotation must update both encrypted fields and bump
`GO2RTC_CREDENTIAL_REVISION` so Fleet replaces the Home Assistant pod. An
authenticated init-container check also holds Home Assistant startup until the
relay API is ready, preventing a one-shot go2rtc connection failure during
simultaneous reconciliation.

Use the browser-resolvable HTTPS hostname for Music Assistant authorization.
Cilium permits the Traefik service only when TLS SNI is `music.media.home`, and
the pod's default CA bundle is extended with the Home Lab Local CA. The
`REQUESTS_CA_BUNDLE` environment variable makes Home Assistant's shared Python
HTTP client use that extended bundle. Jellyfin uses its in-cluster service URL.
Seerr's existing administrator API key is copied into the encrypted
`home-assistant-seerr-api` SopsSecret and injected only into the Home Assistant
pod. It is never exposed to Lovelace. If the Seerr key is rotated, update the
encrypted secret and roll Home Assistant in the same GitOps change. Network
policy permits only Home Assistant-to-Seerr TCP traffic through this path.

## Areas and automations

The guarded source migration preserves existing area IDs while presenting:

- Master Bedroom
- Bedroom
- Guest Room
- Office
- Kitchen
- Dining Room
- Living Room

It validates and assigns all eight Atomberg Aris Gladius devices, writing backups
before any registry change. Its marker prevents later UI edits from being
overwritten.

All existing automations were removed once, after backing up the previous
`automations.yaml`. Subsequent UI-created automations survive restarts. Home
Assistant packages remain enabled for future source-managed automation.

## Validation

Validate the desired resource before delivery with:

```sh
kubectl apply --dry-run=server -f kubernetes/projects/home-automation/apps/home-assistant/helmchart.yaml
```

After Fleet reconciles, inspect the child bundle, Deployment rollout, init
container logs, Home Assistant config check, dashboard files and HTTP health.
