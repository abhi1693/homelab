# Music Assistant Alexa Skill

This companion bundle supplies the service that Music Assistant's Alexa player
provider expects on port `5000`. The player provider can discover Echo devices
through the Amazon account without this service, but queue transfer and direct
play require the separate Alexa Skill Prototype API and an Alexa custom skill.

## Runtime Shape

- Image: `ghcr.io/alams154/music-assistant-skill:0.0.39-beta`
- Internal API:
  `http://music-assistant-alexa-skill.media.svc.cluster.local:5000`
- Public skill and setup endpoint:
  `https://alexa.abhimanyu-saharan.com`
- Public Music Assistant stream endpoint:
  `https://music-stream.abhimanyu-saharan.com`
- Locale: `en-IN`
- Data: retained `1Gi` Longhorn PVC mounted at `/data`

The public skill endpoint is required because Amazon sends custom-skill
requests from outside the LAN. The public stream endpoint proxies Music
Assistant's port `8097`; screenless Echo devices must be able to fetch that
HTTPS URL. Cloudflare Tunnel creates both DNS records and origin routes from the
two `cloudflare-tunnel` Ingress objects.

The skill image is a third-party beta prototype, not part of the Music
Assistant server. Keep it pinned to an immutable digest and re-test playback
before upgrades.

## Persistent State

ASK CLI authorization is stored under `/data/.ask` on the retained PVC. Pod
replacement and node movement therefore do not require another Amazon
authorization. The setup script's generated build and temporary output uses
bounded `emptyDir` volumes at `/app/build`, `/app/tmp`, and `/tmp`.

The application runs as UID/GID `1000`, drops all capabilities, disables
privilege escalation, uses a read-only root filesystem, and has no Kubernetes
API token. Its web UI and Music Assistant-facing API use SOPS-managed HTTP
Basic credentials. Alexa's signed `POST /` skill requests remain accessible
without Basic authentication, as required by the prototype.

## One-Time Alexa Developer Setup

The setup requires an interactive Amazon Developer authorization that cannot be
stored in Git:

1. Create or sign in to the Amazon Developer account associated with the Echo
   account and enable **Skill Access Management**.
2. Read the setup credentials from the generated Kubernetes Secret:

   ```sh
   kubectl -n media get secret music-assistant-alexa-skill-secrets \
     -o jsonpath='{.data.APP_USERNAME}' | base64 -d
   kubectl -n media get secret music-assistant-alexa-skill-secrets \
     -o jsonpath='{.data.APP_PASSWORD}' | base64 -d
   ```

3. Open `https://alexa.abhimanyu-saharan.com/setup`, authenticate with those
   credentials, and start setup.
4. Follow the displayed Amazon authorization URL and paste the returned code
   into the setup page. The service creates or updates the development skill,
   uploads the `en-IN` interaction model, builds it, and enables testing.
5. Open `https://alexa.abhimanyu-saharan.com/status` and confirm that the skill
   exists, its endpoint matches, the interaction model is built, and testing is
   enabled.
6. Retry queue transfer or direct play from Music Assistant. The Alexa
   Developer account and household Echo account must be linked as required by
   Amazon's development-skill testing.

The setup UI reuses the persisted ASK authorization on later visits. Do not
delete the retained PVC unless a full Alexa skill reauthorization is intended.

## Declarative Music Assistant Wiring

The Music Assistant `prepare-provider-runtime` init container preserves the
existing Alexa provider account credentials and sets only the missing
integration values:

- Amazon domain: `amazon.in`, matching the Echo account's `en-IN` region
- Alexa locale: `en-IN`
- API URL:
  `http://music-assistant-alexa-skill.media.svc.cluster.local:5000`
- API username/password: the same SOPS-managed Basic credentials used by this
  service

This removes the provider default `http://localhost:5000`, which otherwise
causes direct play and queue transfer to fail with connection-refused errors.
Music Assistant's core webserver base URL is also pinned to
`https://music.media.home`, so the provider's Amazon authentication proxy opens
under the HTTPS ingress instead of the direct `192.168.3.135:8095` listener.
Amazon's account inventory includes offline devices, so discovery alone is not
a liveness signal. The generated provider overlay initializes each player from
Amazon's `online` flag and polls the shared device inventory at most once every
15 seconds across all Echo players. This bounds online recovery to the next
short poll without making one request per device. A device that goes offline is
marked unavailable and idle; an inventory request failure retains the last
confirmed state instead of declaring every player offline. Each coalesced
refresh also reads Amazon's account-wide volume snapshot. Reported Echo volumes
initialize and update the Music Assistant slider, while a missing volume entry
or failed volume request retains the last confirmed value.
The pinned provider release accepts Amazon login POSTs only below
`/ap/signin/*` and GETs only the proxy root, but Amazon's current challenge
flow uses both methods below `/ap/cvf`, `/ap/register`, `/ap/forgotpassword`,
and the bare `/ap/signin` path. A startup-generated, read-only provider overlay
routes both methods below that temporary `/ap/*` proxy path; it is retained and
recreated declaratively by the Music Assistant bundle.

Start only one authentication attempt and let it complete or time out before
retrying. An Amazon page saying it cannot verify the mobile number is an
account-side trust/risk block when it persists on the correct regional domain,
rather than a Music Assistant validation error. Stop retrying that flow and ask
Amazon Support to clear the verification block before starting one fresh
authentication attempt.

## Status Interpretation

The status page distinguishes deployment health from the two interactive
Amazon gates:

- `testing NOT enabled` means the skill manifest and interaction model exist,
  but the developer account has not enabled the development stage. Open the
  Alexa Developer Console, select **Music Assistant**, open **Test**, and set
  **Skill testing is enabled in: Development**. If Amazon returns `403`, first
  enable **Skill Access Management** for that developer account and confirm the
  same Amazon identity owns the development skill and the Echo household.
- `/ma/latest-url` is idle until Music Assistant successfully discovers an
  Echo player and starts the first direct playback. The player provider then
  pushes its transient stream URL to this API.
- `/alexa/latest-url`, empty APL metadata, and `No recent invocations` remain
  idle until the enabled Alexa skill is invoked. They do not indicate that the
  Flask service or ingress is down. A startup-generated status overlay renders
  these expected `404` responses as yellow idle states while preserving red
  status for unexpected API errors.

After development testing is enabled, authenticate the Music Assistant Alexa
provider again. The `en-IN` deployment uses `amazon.in`; a successful login
creates a retained cookie under `/data/.alexa`, discovers the Echo players, and
allows the first direct-play request to populate both sides of the status page.

## Network Boundary

The Cloudflare connector egress policy permits:

- TCP `5000` to the skill pod for Amazon requests and the setup UI;
- TCP `8097` to Cilium's `remote-node` identity, where host-networked Music
  Assistant serves player streams. A standard pod or CIDR selector does not
  match host-network endpoints.

The stream route intentionally exposes only the stream listener, not the
Music Assistant PWA/API on `8095`. Stream URLs are transient, but the endpoint
must be public for screenless Echo playback.

Official and upstream references:

- <https://www.music-assistant.io/player-support/alexa/>
- <https://github.com/alams154/music-assistant-alexa-skill-prototype>
