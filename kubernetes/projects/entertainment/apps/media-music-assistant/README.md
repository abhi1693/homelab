# Music Assistant

This bundle installs Music Assistant as the listening, discovery,
recommendation, playback, and persistent YouTube Music cache for the music
stack. Account synchronization and cache acquisition run inside the provider;
no separate music acquisition application or bridge is required.

## Runtime Shape

- Namespace: `media`
- Music Assistant: `ghcr.io/music-assistant/server:2.10.0b10`
- Browser URL: `https://music.media.home`
- Direct LAN URL: `http://192.168.3.135:8095`
- Public Alexa stream URL: `https://music-stream.abhimanyu-saharan.com`
- Data: retained `8Gi` Longhorn PVC mounted at `/data`
- Local music: `/library/music` is mounted read-only at `/media`
- YouTube cache: `/library/music/YouTube Music` is mounted read-write at
  `/library-cache/music/YouTube Music`

Music Assistant requires direct Layer 2 access for player discovery and
streaming. The singleton server therefore uses host networking and is pinned to
`k8s-rpi4` (`192.168.3.135`). Players must be able to reach that address,
including the default stream port `8097`. Native Sendspin clients use `8927`;
the browser player uses the authenticated Sendspin path on the main web port.
The Bedroom Google Cast speaker is reserved at `192.168.4.241`. UniFi reflects
its mDNS advertisement across VLANs, while the scoped
`Allow Music Assistant Google Cast` policy permits only TCP `8008`, `8009`, and
`8443` from this Music Assistant host to that speaker. Discovery without that
unicast policy produces a registered player followed by a
`pychromecast.socket_client` timeout on port `8009`.
The Traefik ingress exposes only the PWA/API on `8095`. It terminates HTTPS
with the cert-manager-managed Home Lab Local CA certificate and permanently
redirects browser HTTP requests to HTTPS so WebRTC and credential-bearing
provider flows run in a secure browser context.

The persisted webserver base URL is declaratively pinned to
`https://music.media.home`. Music Assistant still binds unencrypted HTTP on
`8095` inside the LAN, but generated browser callbacks use the TLS-terminating
Traefik origin. This is required by the Alexa provider's proxied Amazon login;
leaving the setting on `auto` redirects authentication to the direct
`http://192.168.3.135:8095` address.

Music Assistant remote access is enabled persistently. Its encrypted WebRTC
gateway connects outbound to the upstream signaling service and uses public
STUN servers for NAT traversal; the local webserver remains private and is not
exposed to the internet.

The upstream project supports HAOS and simple host-networked Docker
installations. Kubernetes is not an upstream-supported installation method.
This deployment deliberately preserves the official container's host-network
shape, persists `/data`, and mounts the existing Kubernetes-managed NFS library
instead of giving the container privileges to mount NFS itself.

The `2.10.0b*` beta line is tracked deliberately because it bundles the newer
MCP provider required for the Connect Wizard through this TLS-terminating
Traefik ingress. The stable `2.9.x` line still bundles an older provider that
cannot safely complete that flow.

## Architecture

Music Assistant merges online and offline sources into one library:

- **YouTube Music** is a declaratively enabled authenticated source for
  catalogue search, personalized Home recommendations, song radio, artist top
  tracks, playlists, albums, and playback. Foreground cache misses stream
  directly without writing or replacing an active player buffer. The native
  background task publishes completed files atomically to
  `/library-cache/music/YouTube Music`; later plays use those retained files
  without consuming YouTube bandwidth. Completed cache files are never purged
  on restart, and cache or catalog failures do not block playback. Its
  authenticated account task mirrors the saved and liked tracks, artists,
  subscriptions, albums, playlists and ordered membership, history window,
  uploads, podcasts, channels, episodes, and account metadata exposed by
  YouTube Music into PostgreSQL.
  Music Assistant library reads use completed mirror snapshots, so transient
  upstream errors do not erase previously mirrored collections.
- **Filesystem (local disk)** indexes the common music tree at `/media`.
  The mount is read-only, so Music Assistant cannot modify operator-managed
  local files. Its configuration is persisted on the retained `/data` PVC.
- **Sonic Analysis (on-device)** analyzes the local files in the background
  with the low-CPU `fast` sampling profile. It stores reusable mood, energy,
  rhythm, timbre, key, and audio-fingerprint data in Music Assistant's retained
  library database; audio is not sent to an external service.
- **Sonic Similarity** turns those analyses into local similar-track results,
  the **Inspired by recently played** Discover row, and the fallback source for
  Radio Playlists. Similar-track radio uses the balanced profile with moderate
  diversity, while the Discover row uses the novelty-leaning profile with
  higher diversity.
- **Radio Playlists** provides **Start Radio** on tracks, albums, artists,
  genres, and playlists. The resulting queue interleaves seed and similar
  tracks, avoids recently heard items, and replenishes itself instead of
  expanding the whole library into a static queue.
- **Last.fm** remains enabled for listening-history recommendations and
  catalog-level similarity hints. The pinned server is overlaid so sparse
  Last.fm results are merged with Sonic Similarity instead of preventing the
  local similarity engine from contributing.
- **Sendspin web player** plays directly in the Music Assistant PWA. Other
  player providers such as Chromecast, AirPlay, DLNA, and Sonos can use the
  same host-networked server.
- **Alexa** uses the separately deployed Music Assistant Alexa Skill Prototype.
  Music Assistant calls its authenticated cluster API, Amazon calls its public
  HTTPS skill endpoint, and screenless Echo devices fetch transient stream URLs
  through the dedicated public port `8097` ingress. Each playback request has a
  correlated command ID, and Music Assistant reports playing only after the
  skill returns `AudioPlayer.PlaybackStarted`. The provider uses stable Amazon
  serial IDs, skips group-like Amazon inventory entries, and coalesces account
  inventory and authoritative volume refreshes to one request every 15 seconds.
  Physical volume-button changes and initial Echo volume therefore update Music
  Assistant without first moving the app slider. Playback is limited to one
  Alexa device per command. An idle Echo cannot be resumed: the provider
  returns the player to `IDLE` without calling Amazon or falsely showing
  playback. Valid resume requests wait for a new correlated playback-started
  event.
When the same item exists in the local and YouTube Music sources, Music
Assistant can link the provider mappings and prefer the highest-quality
available version. Discovery, account synchronization, caching, and online
playback do not require a MusicBrainz album match.

## First Run

1. Open `https://music.media.home` and create the first administrator account.
   Store that password safely; the standalone server cannot recover it.
2. Open **Settings > User Interface** and enable the built-in Sendspin web
   player so **This device** is available as a playback target.
3. Confirm **Settings > Music Sources** contains **Filesystem (local disk)**
   with path `/media`. This provider is persisted on `/data`; enable playlist
   import if you add supported playlist files later.
4. Open a local track, album, artist, genre, or playlist menu and select
   **Start Radio**. The first local-only radios become useful as soon as Sonic
   Analysis has indexed several tracks; coverage grows in the background and
   is visible under **Settings > System > Audio analysis**.
5. Confirm **Settings > Music Sources** shows **YouTube Music**. Fleet reuses
   the browser cookie in the SOPS-managed `music-assistant-secrets` Secret, so
   no second interactive provider setup is required.
6. Allow the initial YouTube and filesystem syncs to finish. Saved songs,
   liked songs, the current history window, playlists, albums, uploads, and
   personalized Home recommendations should then be available.
7. Under **Settings > System > Streams**, verify the detected published address
   is `192.168.3.135`. Set it explicitly if player logs show an unreachable pod
   or service address.
8. For Alexa playback, complete the one-time developer authorization documented
   in
   [`media-music-assistant-alexa-skill`](../media-music-assistant-alexa-skill/README.md).
   Device discovery alone is not sufficient for direct play or queue transfer.

YouTube Music uses an unofficial cookie-based integration because Google does
not provide a supported playback API. Cookies expire and must be replaced in
the SOPS Secret when Music Assistant reports `401: Unauthorized`; increment
the Deployment's `home-lab.io/ytmusic-cookie-revision` pod-template annotation
in the same commit so Fleet restarts Music Assistant and imports the new value.
The custom provider can break when YouTube changes its internal API and is not
supported by Music Assistant upstream.

## Security and Operations

- The Music Assistant YouTube source reads `YTMUSIC_COOKIE` from the
  SOPS-managed `music-assistant-secrets` Secret. The init container encrypts that
  value with Music Assistant's retained Fernet key before inserting the
  provider configuration; the plaintext cookie is not written to Git or to a
  separate provider auth file.
- The main server intentionally has unrestricted host-network access because
  multicast discovery and several player protocols use dynamic TCP/UDP ports.
  It still runs as UID/GID `568`, drops Linux capabilities, uses a read-only
  root filesystem, and does not mount a service-account token.
- The `prepare-provider-runtime` init container creates `/data/provider-venv`
  and preinstalls `yt-dlp[default]==2026.7.4`,
  `ytmusicapi==1.12.1`, and `asyncpg==0.31.0`. The main container directs later `uv` installs to that
  retained virtual environment and adds its site-packages directory to
  `PYTHONPATH`. Package artifacts therefore survive pod replacement without
  making the image filesystem writable. The init container fingerprints the
  Python minor version, Music Assistant version, and managed runtime
  revision, rebuilding the provider environment when any changes so removed or
  outdated packages cannot survive in the retained environment or shadow image
  dependencies.
- The custom provider source is pinned to
  `abhi1693/music-assistant-yt-music` commit
  `fcd8f6aae01d66fe5e8671f2ea50f1d58eb3ab77`. The init container downloads
  that immutable revision when the retained copy is absent or fails its
  expected SHA-256 values, verifies every source file, and stores the source
  unchanged. Production dependency versions remain pinned in the retained
  provider runtime. The main container mounts the result read-only from
  `/data/custom-providers/ytmusic`. Provider code, dependency artifacts, the
  encrypted provider configuration, PostgreSQL account snapshots, and cached
  audio under the media-library NFS path `music/YouTube Music` therefore
  survive restart.
- The module/domain rename is an atomic startup migration. Before Music
  Assistant starts, the init container moves the retained PostgreSQL catalog,
  library mappings and metadata, provider settings, archived listen-history
  path, and persistent player queues to `ytmusic--home`. Derived metadata,
  recommendation, search, and provider cache entries that still reference the
  retired domain are invalidated so Music Assistant rebuilds them. It creates
  `/data/library.db.before-ytmusic-domain-rename.sqlite3` before changing the
  SQLite library and refuses to merge if both provider identities already have
  records. The migration also removes scheduled-task state owned by the retired
  provider instance, including its account mirror, prefetch, and core library
  sync tasks; the renamed instance registers fresh schedules without retaining
  duplicate jobs. The renamed provider source is stored outside
  `provider-patches`; that directory remains only for overlays that actually
  alter upstream Music Assistant or Alexa code.
- The provider registers a native Music Assistant background task that
  prefetches up to 1,000 saved, liked, uploaded, and mirrored-history tracks
  every six hours into that same persistent cache. Production permits three
  concurrent yt-dlp track downloads, staggers their starts by 15 seconds,
  continues while players are active, atomically publishes completed files,
  and stops scheduling work when the cache reaches 50 GiB. Already-started
  files may finish beyond that ceiling. Playlist expansion remains disabled to
  keep the initial bandwidth and storage demand bounded.
- Each run performs a full catalog-to-filesystem reconciliation. A database row
  whose completed file is missing is cleared and requeued with repair priority,
  so stale PostgreSQL state cannot permanently suppress a download.
- Quality upgrades are enabled with a target of 256 kbps and a 30-day recheck
  interval. The authenticated yt-dlp session resolves the best currently
  available audio and replaces an existing cache entry only when the resolved
  bitrate is strictly higher. The old completed file remains playable until
  the new file has been flushed and atomically published.
- Background format resolution and download load the provider's encrypted
  browser cookie into yt-dlp's in-memory cookie jar and reuse the selected
  Google account without writing a plaintext cookie file. Each claim resolves
  once, then downloads that exact media URL. A 15-second delay staggers starts
  within each three-download batch and paces consecutive batches. YouTube
  bot-verification responses stop new batches and persist a six-hour PostgreSQL
  cooldown so pod restarts cannot immediately resume the request storm.
- Background downloads use yt-dlp's resumable range downloader in the retained
  local path `/data/ytmusic-cache-staging`. Completed stages are copied to an
  NFS `.part`, flushed, and atomically published. PostgreSQL claims jobs
  individually until the three-download batch is full, allowing a foreground
  cache miss to receive priority over untouched bulk-library work between
  batches without changing active playback.
- The background task stores its durable queue, cache metadata, attempts,
  leases, and retry schedule in the `music_assistant` PostgreSQL database.
  The provider uses at most two direct database connections and fails open:
  catalog outages are logged but never prevent foreground YouTube Music
  playback. The SOPS-managed database credentials are converted to an
  encrypted provider setting during init and are never committed in plaintext.
- Cache hits expose `local_cache`, `Local cache`, and `cache_hit=true` in
  provider stream details and emit `Playback source: Local cache` in the
  Music Assistant log. Remote first plays expose `youtube`, `YouTube Music`,
  and `cache_hit=false`, providing an explicit regression signal if a future
  implementation bypasses the persistent cache.
- Foreground cache misses always remain ordinary HTTP streams. Only the native
  background task writes cache files, so publishing a completed file can never
  replace an active or preloaded Music Assistant audio buffer.
- The same init container declaratively keeps the MCP Connect Wizard's external
  URL and allowed origin on `https://music.media.home` and enables the
  provider's opt-in trusted forwarded-scheme handling. Traefik terminates TLS
  and overwrites the forwarded scheme before proxying to Music Assistant. Keep
  port `8095` as an operator-only direct endpoint and use the HTTPS ingress for
  the Connect Wizard.
- WebRTC remote access is also kept enabled in the persisted core settings.
  This starts Music Assistant's outbound signaling gateway without publishing
  the local webserver through a WAN ingress.
- Sonic Analysis and Sonic Similarity are also inserted into the retained
  provider configuration on every start. The server image already contains
  their pinned ARM64-compatible dependencies, so no restart-time package
  download is required. Character indexing and natural-language search remain
  disabled: radio uses the inexpensive traits index, and the optional text
  encoder's roughly 500 MiB download is avoided.
- Hugging Face requests use `HF_TOKEN` from the SOPS-encrypted
  `music-assistant-secrets` Secret. The token is never stored in the Deployment
  or committed as plaintext; model artifacts remain cached under
  `/data/.cache/huggingface`.
- The init container creates a guarded overlay for Music Assistant's
  similar-track controller. It merges results from metadata and plugin
  providers so the occasional sparse Last.fm match does not short-circuit the
  local Sonic result set. The overlay generation fails closed when an upstream
  upgrade changes the expected controller block.
- The init container also keeps the Alexa player's regional Amazon domain
  (`amazon.in`), `en-IN` locale, authenticated prototype API URL, and API
  credentials declarative. Its provider overlay adds the missing `en-IN`
  configuration option and English invocation phrase to the pinned beta. It
  does not replace the Amazon account password or MFA state stored by the
  provider.
- The same init container pins the core webserver base URL to the HTTPS ingress
  so provider authentication helpers do not emit direct-IP callback URLs.
- Alexa's successful-login handler must notify Music Assistant's temporary
  authentication callback itself. The pinned beta registers one wildcard setup
  proxy route below `/setup_flow/alexa_proxy/<flow-id>/`, but still sends that
  server-side notification to the browser-facing HTTPS URL. The container does
  not trust the private issuer for `music.media.home`, causing the final sign-in
  POST to return `500`. The setup-flow overlay keeps the browser-facing
  callback on HTTPS while sending this internal notification to Music
  Assistant's plaintext loopback listener on the webserver controller's
  configured publish port. The main container mounts the patched provider and
  setup-flow files read-only. The init container fails if upstream changes the
  expected blocks, making upgrades reviewable instead of silently carrying a
  stale patch.
- Do not start another Alexa authentication while one is pending. Dynamic
  routes remain registered until the active helper completes or times out, so
  overlapping attempts fail with `Route /alexa/auth/proxy/ already registered`.
  Amazon's `We're unable to verify your mobile number` loop is a separate
  Amazon account trust/risk block reported across unofficial Alexa clients;
  stop retrying and ask Amazon Support to clear the account verification block.
- `alexapy.errors.AlexapyTooManyRequestsError` during rapid player controls is
  Amazon throttling the unofficial account API. `alexapy` backs off and retries
  the request. Avoid repeated clicks while it is retrying; invalid resume
  requests are rejected locally and no longer consume another Amazon request.
- `Accepting unencrypted legacy connection (transition mode)` from
  `aiosendspin` is the local Music Assistant Companion connecting over
  `127.0.0.1`. It is unrelated to Alexa and does not expose that connection
  beyond the pod's loopback boundary.
- `k8s-rpi4` must keep `8095`, `8097`, and `8927` available. If the server is
  intentionally moved, update the node selector and documented address
  together.
- The PVC is retained by Helm/Fleet policy. Back up `/data` before destructive
  recovery because it contains the Music Assistant database, provider
  configuration, authentication state, cached metadata, the persistent provider
  virtual environment, the Alexa provider overlay, and the Smart Fades PyTorch
  model cache. `TORCH_HOME` points at `/data/.cache/torch`, while `HOME` and
  `XDG_CACHE_HOME` keep dynamically installed provider caches under `/data`.
  Model and yt-dlp cache writes therefore remain persistent and writable while
  the container root filesystem stays read-only.

Official references:

- <https://www.music-assistant.io/installation/>
- <https://www.music-assistant.io/music-providers/youtube-music/>
- <https://www.music-assistant.io/music-providers/filesystem/>
- <https://www.music-assistant.io/usage/#radio-mode>
- <https://www.music-assistant.io/audio-analysis/sonic-analysis/>
- <https://www.music-assistant.io/plugins/sonic-similarity/>
- <https://www.music-assistant.io/metadata-providers/lastfm-recommendations/>
- <https://www.music-assistant.io/player-support/sendspin/>
- <https://www.music-assistant.io/player-support/alexa/>
