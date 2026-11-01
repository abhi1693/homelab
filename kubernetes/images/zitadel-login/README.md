# Zitadel Login registration repair

This image builds Zitadel Login v4.20.0 from commit
`8afa5dd37a8e723efb9eace8d09fd5c1cccef694` with one source patch: after
successful user creation and identity-provider linking, retry session creation
on `NotFound` after 500 ms, 1 s, and 2 s. User creation and identity linking are
never retried. Permission, authentication, and all other errors propagate.

The retry covers session-projection delay in `registerUserAndLinkToIDP`, which
the upstream password-registration retry does not cover. The Docker build
checks patch anchors and runs recovery, rejection and exhaustion tests before
publication. An account whose creation/linking succeeded should start a fresh
provider sign-in; do not delete or recreate it to retry session lookup.

The Dockerfile, committed workspace/lockfile and `dependency-policy.json` define
source/runtime pins and reviewed dependency floors. The standard-library policy
guard rejects stale resolutions, mismatched workspace/lock overrides, duplicates,
missing entries and unreviewed major/prerelease changes. It runs before the real
frozen-lockfile installation; compilation, runtime scanning and smoke tests remain
separate release gates. Package managers are removed from the runtime.

Runtime source remains strictly type-checked; integration/test fixtures run
through their own checks. The custom image changes Login only. Qualify Core and
its embedded Console independently, and keep Login dependency changes separate
from Core database migrations.

Run the source checks with:

```sh
python3 kubernetes/images/zitadel-login/check-dependency-policy.py
python3 -m unittest discover --start-directory kubernetes/images/zitadel-login/tests -v
```
Pull requests and Renovate branch pushes run the source checks and a native
ARM64 image build, scan and smoke without publishing. A scoped Renovate rule
requires these checks before source updates can automerge; the global policy
hook runs the dependency regressions when its configuration changes. The shared
publisher is pinned to its reviewed commit. Only default-branch builds and
manual builds of `master` publish immutable
`4.20.0-idp-retry2-<commit>` tags after native ARM64
build, runtime vulnerability scanning, and smoke tests. The shared publisher
normalizes the metadata prefix by removing the leading `v`. The runtime smoke reads
[`runtime-policy.json`](runtime-policy.json) to enforce minimum Node 26.12.1 and
Next.js 16.4.1 within the reviewed major versions. It checks that a fresh TLS
trust store excludes the configured distrusted CA fingerprints, then starts the
standalone Login server and checks its local health without production identity
credentials. Existing fixed release tags
remain immutable.
Deployment is separate: only update the Fleet values after this build succeeds.
Rollback to upstream `ghcr.io/zitadel/zitadel-login:v4.20.0` removes the retry
protection; retain the custom image digest for a subsequent rollback.
The custom Login patch adds no database migration or change to identity-linking
authorization.

The production TypeScript project excludes test fixtures (which predate the
patched Next.js compiler); strict checking remains enabled for all runtime
source. Vitest runs the bounded-retry regressions separately in the image build.

Login v4.20.0 signs session cookies. Configure `ZITADEL_SESSION_COOKIE_SECRET`
from the same SOPS-managed secret on every replica. Existing unsigned Login UI
cookies are rejected once after upgrade; application sessions and issued tokens
are unaffected. The core upgrade runs database setup migrations, so a core
downgrade requires a separate database compatibility review.
