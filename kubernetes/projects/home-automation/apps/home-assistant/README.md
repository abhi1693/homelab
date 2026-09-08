# Home Assistant

Home Assistant is installed through the upstream `pajikos/home-assistant` Helm
chart. Rancher Fleet reconciles this directory and K3s' Helm controller installs
the resulting `HelmChart` resource.

- endpoint: `http://ha.home`
- chart version: `0.3.75`
- app version: `2026.9.1`
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

The `archive-sqlite-recorder` init container preserves pre-PostgreSQL SQLite
data under `/config/backups/recorder-sqlite-pre-postgresql-20260814`, guarded
by a marker. It remains in the manifest for recovery/bootstrap compatibility.
Its `32Mi` request and `384Mi` limit cover file-copy cache usage.
This archive is not imported PostgreSQL history and is not a current backup.
Review it before cleanup; never overwrite live Recorder files during recovery.

## Application source

Portable Home Assistant source is owned by the public
[`abhi1693/home-assistant`](https://github.com/abhi1693/home-assistant)
repository. This deployment pins commit
`84baef94a154e23f5a1eb71581ad1ab03bfe3f5c` and the SHA-256 of its GitHub source
archive. The `install-home-assistant-source` init container verifies the archive
before running its standard-library-only bootstrap against `/config`.

The source repository owns dashboard layout, integration code and asset pins,
family account/room mappings, camera and health-data access policy, automations,
and application bootstrap. Its documentation is authoritative for those
features; this README covers deployment and infrastructure dependencies.

This repository owns only Kubernetes/Fleet concerns: chart values, persistence,
ingress, policies, registry credentials and local CA trust. Update the source
commit, archive checksum and `HOME_ASSISTANT_SOURCE_REVISION` together to deploy
a new Home Assistant source revision. The environment value deliberately changes
the pod template and triggers a `Recreate` rollout.

## User-facing access

The family dashboard is `http://ha.home/home-tablet/home`; Rack is admin-only.
Family camera, calendar, location, and health-data grants are backend-enforced
by the pinned application source, not merely hidden in dashboards. Preserve
those policies when changing integrations or source revisions.

`http://ha.home/home-tablet/finance` adds an Abhimanyu-only finance view using
adapted MIT-licensed netwrth cards and a GET-only Firefly III adapter. It shows
INR ledger history, monthly spending, savings/payment charts, subscription schedules, and
credit-card payments without a PIN. The shared period selector supports months,
January–December calendar years, April–March financial years and custom date
ranges. All panels use the same charts with period totals, daily/monthly trends and
optional month/year comparisons. Month view lists earlier months newest first,
back to the first recorded month. Completed months compare in full; the current
month uses matching days elapsed, including on its final day. Charts align by day number, retain all days
from longer months, and show the original dates in tooltips. Spending and income
comparisons use paired daily bars in Month view; whole-period totals stay above
the chart. Daily amounts reconcile with the authorised transaction feed and
exclude self-transfers, with hover, keyboard and tap tooltips. Annual/custom
comparisons use matching elapsed calendar dates; future commitments remain
separate. Balances are snapshots at the
period end or today. The net-worth summary follows every selected period,
including months; its tooltip explains the closing balance and change from the
previous day's closing balance before the period began. The net-worth history
chart retains its own range in ordinary Month mode and follows the shared
period in annual/custom and comparison views.
Year/comparison options and date navigation start at the first recorded Firefly
transaction, including its containing financial year. The available history is
discovered with a cached read and updates when older records are imported.
Its summary separates Cash & bank, Investments and Negative balances, with
account details on hover, focus or tap. The change badge explains both comparison
dates, balances and the rupee/percentage calculation. Negative ledger balances
are not automatically described as debt. The private investment classification
includes the five imported CAMS valuation accounts, alongside the existing
investment accounts; reconciliation entries do not become contributions or income.
Spending shows the eight largest named categories, with the remainder combined
into Others and Uncategorised kept separate when present. Each displayed group
has a distinct color shared by the donut and list. Others expands to its member
spending transactions with their original category labels. Details stay within
the selected category column, preserving its neighbor's position and width.
Savings & spending replaces the account tiles with savings balance history for
HDFC, Digibank and SBI, plus daily/monthly purchase bars split between direct
savings payments and credit cards. Other accounts appears only for purchases
outside those groups, so the method totals still reconcile to spending.
Account filters change the savings line; selecting a payment method expands its
contributing accounts without showing their ledger balances. Repayments,
own-account transfers and investment contributions are excluded from purchases.
Savings and payment charts support hover, keyboard arrows and touch/pen taps
for exact dated values, including the matching comparison period. Tap tooltips
stay open until dismissed or another point is selected, and remain within the
panel without adding scrollbars.
Year comparisons reuse the charts with a dashed savings line and faded purchase
stacks. Every chart fits its panel without horizontal or vertical scrolling.
Bars scale to the available width, axis labels thin out on smaller screens,
and tooltips retain the exact dates and amounts. Mobile charts stack; all
months stay plotted even in multi-year views. Empty bill schedules stay compact
in their own section.
Income includes salary, royalties, refunds, family credits and other external
deposits, with one Sources breakdown of dated transactions grouped by sender.
Self-transfers and card repayments are excluded from income and its sources,
including reviewed historical deposits configured by journal ID in the source
repository. The filter preserves Firefly ledger records and account balances.
Each data panel has an independent loading/refresh spinner; background
refreshes keep current figures visible. Expanded income and category details
show their spinner inside that section.
Recurring bills sum only recorded payments and remaining due dates in the
selected period; annual bills appear in their due month and future starts do
not inflate today's total. The Investments panel shows a compact contribution
donut grouped by investment label, separate recorded/pending totals, and income
after the period's commitments. Provider labels are an informational legend;
the redundant dated payment list and expand controls are removed. Annual trends
and month/year comparisons remain visible; the donut includes both recorded and
scheduled contributions.
`finance-investments.yaml` owns the private account classifications and current
plans, mounted read-only at `/finance/investments.json` and selected with
`FAMILY_FINANCE_INVESTMENT_FILE`. Keep actual household amounts in this private
repository; the public source contains only generic schedule support. Current
plans begin September 2026: Groww monthly on the 1st and SafeGold weekly on
Tuesday. The former additional monthly contribution is not scheduled. Weekly
counts follow the actual calendar. Existing Razorpay debits are currently
recorded against Firefly's Groww investment account, so SafeGold's matcher uses
that account plus its distinct narration. Recorded payments also receive the
provider label when source, destination, amount and narration match uniquely,
even before the current schedule starts; August's weekly payments display as
SafeGold. Labels do not settle forecasts or rewrite ledger records.
These schedules create no transactions. Matching imported contributions replace
planned amounts once; statement dates or narrations outside the matching window
need review. Update the source revision or pod-template revision through Fleet
when changing this startup-loaded configuration.
Net-worth exclusions do not hide accounts or their credit-card history. The
backend checks the exact active HA user; native Firefly sensor entities are
excluded from other family grants.
Configure the built-in Firefly III integration using `http://finance.home:80` and
a personal access token. The adapter reuses that saved connection; no extra
Kubernetes secret is required. Until a connection is saved, the cards show setup
guidance. Chart payloads are not recorded as entities by the adapter.

Protect video uses the dedicated
[go2rtc relay](../home-assistant-go2rtc/README.md). Home Assistant reaches the
private signaling API; the relay fetches RTSPS from the UDM at
`192.168.1.1:7441` and Protect Storage at `192.168.1.174:7441`.
LAN browsers use `192.168.3.17:8555/TCP,UDP` for WebRTC media. Protect API
access uses TCP `443`; speaker-capable cameras need the separately scoped
TCP `7004` path. Keep recorder and camera destinations explicit.

Companion App external sensor delivery uses the
[mobile webhook gateway](../home-assistant-mobile-webhook/README.md), not public
access to the Home Assistant UI or API.

## Network and service integrations

Reverse-proxy HTTP configuration is UI-owned under `Settings > System > Network`;
there is no deprecated top-level `http:` YAML block.

Home Assistant has narrowly scoped service paths:

- go2rtc signaling: `http://home-assistant-go2rtc.home-assistant.svc.cluster.local:1984/`
- go2rtc WebRTC media: `192.168.3.17:8555/TCP,UDP`
- Music Assistant: `https://music.media.home`
- Jellyfin: `http://jellyfin.media.svc.cluster.local:8096`
- Seerr: `http://jellyseerr.media.svc.cluster.local:10241`
- Firefly III: `http://finance.home:80`, or directly at
  `http://firefly-iii.finance.svc.cluster.local:8080`

Firefly III uses paired NetworkPolicy rules: egress from the Home Assistant
application pods and ingress to the Firefly web pods, both limited to TCP 8080.
The LAN hostname has a separate Cilium service rule for Traefik's HTTP ports
80/8000, restricted to host `finance.home` and `GET /api/v1/*`. This also allows
the native integration's setup check through the hostname; permitting the
direct Firefly service alone does not permit the ingress route. An unauthenticated
`GET /api/v1/about` with `Accept: application/json` should return HTTP 401
promptly; a timeout indicates a connectivity problem, while 401 confirms the
API still requires a token.

Keep the explicit `:80` in the native integration's URL: the `pyfirefly` version
bundled with Home Assistant 2026.9.1 defaults to port 9000 when the URL omits its
port, even for `http://finance.home`. Browsers use port 80 for the same bare URL.
Verify connectivity with the integration's own `Firefly.get_about()` client
when troubleshooting setup; a browser or generic HTTP probe alone misses this
client-specific default.

The go2rtc API credentials come from the SOPS-encrypted
`home-assistant-go2rtc` Secret and are never exposed to dashboard browsers. A
credential rotation must update both encrypted fields and bump
`GO2RTC_CREDENTIAL_REVISION` so Fleet replaces the Home Assistant pod. An
authenticated init-container check also holds Home Assistant startup until the
relay API is ready, preventing a one-shot go2rtc connection failure during
simultaneous reconciliation.

Use the browser-resolvable HTTPS hostname for Music Assistant authorization.
Cilium permits Traefik HTTPS only when TLS SNI is `music.media.home`, and
the pod's default CA bundle is extended with the Home Lab Local CA. The
`REQUESTS_CA_BUNDLE` environment variable makes Home Assistant's shared Python
HTTP client use that extended bundle. Jellyfin uses its in-cluster service URL.
Seerr's existing administrator API key is copied into the encrypted
`home-assistant-seerr-api` SopsSecret and injected only into the Home Assistant
pod. It is never exposed to Lovelace. If the Seerr key is rotated, update the
encrypted secret and roll Home Assistant in the same GitOps change. Network
policy permits only Home Assistant-to-Seerr TCP traffic through this path.

## Persistent configuration

The source bootstrap validates retained registry identities before applying
room and account mappings. UI-created automations persist across restarts.
Keep configuration backups and migration markers until their recovery value has
been reviewed; do not rerun historical resets against the current installation.

## Validation

Validate the desired resource before delivery with:

```sh
kubectl apply --dry-run=server -f kubernetes/projects/home-automation/apps/home-assistant/helmchart.yaml
```

After Fleet reconciles, inspect the child bundle, Deployment rollout, init
container logs, Home Assistant config check, dashboard files and HTTP health.
