# Personal Blog credential cutover

This workflow rotates Blog's Resend credential and runtime CRON secret through
Git and Fleet. Sanity's required Viewer token remains unchanged, including its
server, Studio and authenticated Draft Mode preview capabilities. The helper has
no Sanity mutation endpoint. Preparation and offline tests do not authorize or
execute a production cutover.

The helper is
[kubernetes/projects/applications/apps/personal-blog/scripts/credential_cutover.py](../../kubernetes/projects/applications/apps/personal-blog/scripts/credential_cutover.py).
It uses Python, PyYAML, SOPS, the normal GitHub CLI authentication, and a reviewed
read-only Kubernetes context. Use an explicit reviewed
`--ssh-host asaharan@<private-control-plane-IP>` for the cutover commands; the
retirement audit requires that trusted control plane and has no local-context fallback. No Kubernetes
mutation, Git commit, push, merge, restart, scale operation or Job creation is
implemented by the helper. Provider creation/deletion and GitHub secret deletion
are explicit later stages for the authorized Blog phase.

## Known boundary and required inputs

The managed resource is `SopsSecret/personal-blog-secrets` in `personal-blog`.
Its single `Opaque` template creates `Secret/personal-blog`, with base64 `data`
fields encrypted under the repository's existing age recipient and
`^(data|stringData)$` policy. The Deployment reads that Secret with `envFrom`;
`CronJob/personal-blog-newsletter` reads its `CRON_SECRET` field. Do not create a
separate `personal-blog-runtime` Secret.

Before a cutover, verify the exact published image's immutable index, ARM64
manifest/config evidence, native checks and source commit. Merge the reviewed source
workflow hardening first: runtime CRON/Resend credentials must no longer pass
through CI or workflow artifacts. Record its actual merged commit. The helper's
`cleanup-ci` stage verifies that commit is an ancestor of current source master,
that the complete workflow/local-action/script path and blob inventory is still
the reviewed one, and that no queued or running Blog workflow remains.

The old Resend key ID must be the exact sole key returned by the current runtime
credential. The initial October 23 metadata inventory found one key and only
Blog's encrypted manifest among Git-tracked YAML references to the Resend key
name. This is not a cross-namespace value comparison or proof that no external
consumer exists. Establish the exact account/key ownership before revoking it.
The retirement helper additionally requires a fresh bounded in-cluster equality
audit on an explicitly selected trusted control plane (`--ssh-host` is required
for retirement). It discovers only Secret namespace/name/type/key-name metadata,
then reads only selected email/provider/env/config fields in private remote memory.
TLS, ServiceAccount, registry, SSH, bootstrap and Helm release types are excluded.
The auditor has fixed count, size and time bounds and rejects changed snapshots.
Its only output is counts, matching Secret/key identities and completion/error
flags. It does not decode every Secret or establish absence from arbitrary
unselected fields or external consumers.

After Blog switches to its new credential, the audit compares the **old encrypted
journal value**, sent through private stdin, and independently requires Blog's
current Secret to equal the **new** journal value. Reading the new Blog value as
the comparison target would miss old-key consumers. Any old match, error,
incomplete result, unexpected output or unstable snapshot blocks retirement.
A previous saved clear audit cannot substitute for the fresh retirement check.
The app creates, lists and removes contacts as well as sending email. A
`sending_access` replacement would break those existing contact features; this
workflow creates a dedicated `full_access` app key under Resend's current scopes.

The source sender domain previously reported `failed`. Record it as a newsletter
limitation. Do not trigger domain verification, repair DNS, send a test email, or
claim mailing readiness as part of this package cutover. This limitation alone
does not prevent the public web package upgrade.

## Private recovery and retries

Use a new private state directory outside the repository for each rotation. The
helper requires mode 0700 and rejects symlinked recovery paths. Recovery/lock
files must be owned by the operator, mode 0600, regular and singly linked. Do not
copy a recovery journal into Git, CI, a report, or a public artifact.

A synthetic encryption/decryption roundtrip uses the actual manifest filename,
configured recipient and encryption selector before production credential
capture. Every protected output leaf must be encrypted; an encrypted SOPS MAC
alone is insufficient. No production plaintext file, token argument, provider
response dump, or raw subprocess error is emitted.

The encrypted journal holds only the old/new Resend material needed for safe
cutover and rejection proof, one newly generated 32-byte CRON value, and encrypted
baseline hashes for the three untouched fields. Sanity's credential is not copied
into that journal. The one-time replacement response is encrypted, fsynced and
atomically recorded before propagation. Repeating `capture` reuses the same CRON;
repeating `create-resend` after capture performs metadata reads instead of a
second creation.

There is an unavoidable provider-commit-to-response-capture gap. A request timeout
or a crash after creation can leave an orphan key whose secret cannot be
retrieved. A durable intent written before POST fences every automatic retry
without a captured response. Do not delete/reset the journal, replay POST, or
create a fresh state directory to bypass this latch. Resolve the exact orphan
with independent provider authority, revoke it if necessary, and review a new
attempt. The old Resend key is kept active throughout this uncertainty. Local
encrypted persistence is not a distributed transaction or crash-proof capture.

## Authorized cutover sequence

First merge/reconcile the workflow foundation, including the permanent newsletter
`timeZone: Asia/Kolkata` contract, before any credential capture or provider write.
`capture` and `create-resend` both require that live timezone, a clear schedule
window and no active newsletter Job.

Use nonsecret values for these variables. For this K3s contract, the expected Pod
`status.imageID` digest is bound to the
immutable image index pin. It is not the ARM64 config digest. Verify the ARM64
manifest/config independently through the native release proof; an unexpected
containerd identity format fails closed and needs review. The helper also binds
Pod `status.containerStatuses[].image` to the independently verified ARM64 config
digest; input expectations are not a substitute for the native release proof.

```sh
CUTOVER=kubernetes/projects/applications/apps/personal-blog/scripts/credential_cutover.py
STATE_DIR="$HOME/.local/state/home-lab/blog-credential-cutover/<rotation-id>"
SSH_HOST='asaharan@<reviewed-private-control-plane-IP>'
IMAGE='<verified registry.home/ghcr.io/abhi1693/personal-blog:version@sha256:index>'
EXPECTED_POD_IMAGE_ID='sha256:<same verified index digest as IMAGE>'
EXPECTED_CONFIG_DIGEST='sha256:<verified ARM64 config digest>'
SOURCE_GUARD_SHA='<reviewed merged source commit>'
OLD_KEY_ID='<exact sole existing Resend API-key UUID>'

python3 "$CUTOVER" preflight --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" check-window --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" capture --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST" \
  --image "$IMAGE" --expected-pod-image-id "$EXPECTED_POD_IMAGE_ID" \
  --expected-config-digest "$EXPECTED_CONFIG_DIGEST" \
  --source-guard-sha "$SOURCE_GUARD_SHA" --old-key-id "$OLD_KEY_ID"
python3 "$CUTOVER" create-resend --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
```

`capture` privately binds the existing runtime Resend value to the encrypted
GitOps source and sole provider key metadata. It generates and encrypts CRON
once. `create-resend` saves an intent before POST and encrypts the one-time result
before verifying replacement key metadata with the new credential. These stages
do not change the application or its runtime Secret.

Perform the cutover outside the newsletter's scheduled Friday 18:00
Asia/Kolkata window (12:30 UTC). The CronJob's permanent explicit
`timeZone: Asia/Kolkata` preserves the configured node timezone and observed
October 16 12:30 UTC execution; wait for that timezone contract to reconcile
through Fleet before secret propagation. Missing or changed live timeZone fails
closed. Kubernetes otherwise uses the controller's local timezone.
The helper refuses secret preparation and rollout preparation from 17:30 through
18:29 Asia/Kolkata on Friday (12:00–12:59 UTC) and while any newsletter Job is
active. It never suspends the
CronJob or invokes its endpoint. Run `check-window` freshly immediately before
each GitOps push; do not prepare a Secret change and propagate it hours later
without checking again.

```sh
python3 "$CUTOVER" write-secret --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" check-window --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
```

Review and commit **only the encrypted Secret change** as the first permanent
GitOps change. `write-secret` replaces only `RESEND_API_KEY_FULL` and `CRON_SECRET`;
it verifies and preserves the other fields, including Sanity's required token.
Commit/push using the normal repository workflow and wait for Fleet. Do not apply
or patch a live Secret. Updating GitHub secrets is not runtime propagation.

```sh
python3 "$CUTOVER" observe-secret --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" prepare-rollout --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" check-window --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
```

`observe-secret` requires the original Secret UID, changed resourceVersion and
private equality of both new field values. ResourceVersion alone cannot pass.
`prepare-rollout` checks actual Secret values again, then changes only the web
image and durable `home-lab.io/credential-revision` annotation. Review, commit and
push that Deployment change as the second permanent GitOps change. The helper
preserves the Deployment's formatting and Renovate tracking comment, and rejects
an edit if its parsed result changes any other field. Let Fleet
perform its normal rollout; no manual restart is needed.

Wait for Fleet desired=applied, the reviewed release image/config, one healthy web
Pod, zero restarts, no old web Pod, and at least 120 seconds of stable readiness.
The helper binds Deployment UID, ReplicaSet ownership, Pod UID, immutable image/index, ARM64 config
identity and credential revision, then compares actual Pod environment fields
through private stdin to Node. Only equality booleans and nonsecret identities
return. Sanity is also checked against its preserved source baseline; it is
never stripped to make a build or probe pass.

```sh
python3 "$CUTOVER" observe-pods --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" retire-resend --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" cleanup-ci --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
python3 "$CUTOVER" seal --state-dir "$STATE_DIR" --ssh-host "$SSH_HOST"
```

`retire-resend` repeats real readiness/environment checks, verifies the new key's
metadata identity, performs that fresh old-key consumer audit and deletes only
the captured old key ID with the new key. If another selected Secret still holds
the old value, migrate its known consumer through its own reviewed workflow and
repeat the audit; do not bypass the gate or blanket-rewrite other Secrets.
It requires that ID to disappear and old-key metadata authentication to return
the documented HTTP 400 `validation_error` with exactly `API key is invalid`,
while the new credential retains HTTP 200 metadata access. Other HTTP 400
validation failures, missing/restricted-key responses and edge rejections cannot
pass. Only the recognized rejection flag is retained; raw provider error bodies
are never returned or printed. No contact or email
operation is used for validation. `cleanup-ci` removes only obsolete repository
`CRON_SECRET` and `RESEND_API_KEY_FULL` records after source/active-run checks; it
never deletes `SANITY_API_READ_TOKEN`. Deleting a GitHub record is not provider
revocation. `seal` rechecks readiness and removes credential copies from the
private encrypted journal after retirement and CI cleanup, retaining safe audit
metadata. Retain only that sealed receipt as needed.

Do not call `/api/newsletter/send` with an old or new CRON value to test rotation:
it can send mail when accepted. Do not use unsubscribe GET routes as probes.
The fresh Secret/Pod equality checks, CronJob reference, absence of active old
Jobs and source authorization contract establish CRON propagation without a send.

If the new image fails, keep the new credential material and use a reviewed Git
change to run the last healthy image with the new credential revision. Do not
restore the exposed old secrets or revoke the old provider key before a healthy
Pod consumes the replacement. The Secret-first interval can reject a scheduled
newsletter request until the web rollout completes; there is no uninterrupted
newsletter claim. Complete/recover that normal rollout before the send window.

## Sanity remains explicitly blocked

The observed runtime identity is a Viewer robot with `readAll`. It cannot list
project robots (403), while the existing private owner CLI session returns 401.
The helper implements **no Sanity create, rotate, revoke or GitHub-token update**
and has no boolean bypass for this boundary.

A separate Sanity cutover requires a fresh authenticated project authority,
successful official project and token-management metadata reads, and documented
independent recovery access. Prefer creating a new dedicated Viewer robot with
overlap, privately capturing its one-time response, updating the exact GitHub
`SANITY_API_READ_TOKEN` through stdin or a sealed-box API, and updating its SOPS
field through Git/Fleet before revoking the old token. Never place its value in
`gh secret set --body <value>`, a shell assignment, arguments, plaintext files or
logs. Preserve Studio and authenticated preview behavior. New project-token
creation may notify project administrators under Sanity's provider policy.

Sanity's self-rotation endpoint immediately invalidates the old robot token and
returns its replacement once, with no overlap. A lost response can remove the
only working credential; encrypted local journaling cannot repair that loss.
Do not invoke it with the current expired owner session. Review any future
self-rotation only after independent privileged recovery authority is established.
Until then, report Sanity rotation/revocation as **blocked**, even when the web
package upgrade, Resend/CRON cutover and artifact workflow mitigation complete.

Official references: [Kubernetes CronJob time zones](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#time-zones),
[Resend authentication error contract](https://resend.com/docs/api-reference/errors),
[Resend key creation and permissions](https://resend.com/docs/api-reference/api-keys/create-api-key),
[key deletion](https://resend.com/docs/api-reference/api-keys/delete-api-key), and
[Sanity Access API authorization, rotation and revocation](https://www.sanity.io/docs/http-reference/access-api).

## Verification

```sh
python3 -m unittest discover -s kubernetes/projects/applications/apps/personal-blog/tests -v
```

The fixtures use disposable files and fake provider/subprocess responses. They
cover unknown creation outcomes, failed encrypted capture, safe retries, SOPS
selectors, unchanged preview credentials, actual Secret/Pod equality, release and
ownership drift, active newsletter jobs, scheduled-window fencing, CI guard drift,
restricted deletion and encrypted-copy cleanup. They do not create provider keys,
change GitHub secrets, contact a cluster or send mail.
