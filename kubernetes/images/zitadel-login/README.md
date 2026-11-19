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

The November security refresh pins Zod 4.6.6, Undici 6.29.1/7.30.1,
Joi 18.3.1, follow-redirects 1.16.2, systeminformation 5.33.16,
body-parser 1.20.9/2.4.0, fast-uri 3.1.9, qs 6.16.1 and
`@hono/node-server` 2.1.6. Existing package major versions are preserved.
The November 13 patch raises the Hono Node server floor to 2.1.6 for
GHSA-qv5m-9pm6-hqp3 and GHSA-jpvv-r467-5p4w. The existing MCP SDK
transitive dependency is retained; no other package resolutions change.

Remaining reviewed Dependabot findings are not dismissed: minimatch
GHSA-g3hv-75wg-m249 and glob GHSA-3g3m-2fjr-6pw4 need cross-major
upgrades across the upstream build toolchain (including Nx, ESLint and npm
packaging tools), requiring compilation and compatibility qualification rather
than blanket overrides. Login also directly depends on deepmerge 4.3.1;
GHSA-gcqx-w48m-w2h4 has no patched version in the advisory as of November 13.
A source-level replacement or reviewed upstream patch is needed for that
finding. Repository remediation alone does not update the deployed Login image.

Regenerate the lockfile with the Dockerfile's pinned pnpm against the pinned
upstream source after applying `patch-register.py`, including its test-only
dependency removals. Verify a frozen lockfile-only install against that patched
source before committing; never edit resolved integrity hashes manually. Source and
runtime checks must pass before deploying a newly published image.

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
