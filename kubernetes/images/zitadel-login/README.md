# Zitadel Login registration repair

This image builds Zitadel Login v4.19.4 from commit
`101343ad87aef7b0eea7c3522d519308e0ea9547` with one source patch: after
successful user creation and identity-provider linking, retry session creation
on `NotFound` after 500 ms, 1 s, and 2 s. User creation and identity linking are
never retried. Permission, authentication, and all other errors propagate.

The upstream password registration retry (zitadel/zitadel#12189) does not cover
`registerUserAndLinkToIDP`. On 2026-09-14 production created an account and its
GitHub link successfully, but the immediate session lookup returned
`QUERY-Dfbg2`; resubmitting registration then returned `V3-DKcYh` (duplicate).
Both user lookup APIs subsequently returned the active account.

The Node 26 build installs pinned pnpm 10.30.3 directly because Corepack is no
longer included in that base image. The Docker build checks the patch anchors,
compiles the upstream application,
and runs focused recovery, rejection, and exhaustion tests before publication.
The runtime retains the upstream entrypoint, certificate handling, and user.
It uses a refreshed Node 26 Alpine base, with package managers removed from the
runtime. The committed pnpm lockfile pins patched Next.js, gRPC, telemetry,
archive, and HTTP dependencies required by the runtime security scan, including
Next.js 16.3.8 and gRPC JS 1.14.5.
Nx also requires an Axios 1.20.0 override to avoid introducing an older
vulnerable HTTP client. Toolchain security updates pin Nx 22.7.10, Piscina
5.3.2, shell-quote 1.11.0, Joi 18.2.9, smol-toml 1.9.0, source-map-js 1.2.2, and
the Vitest 4.1.11 family. Brace expansion stays in the existing 1.x, 2.x, and
5.x API families, and js-yaml stays in 3.x and 4.x.
Web security updates pin Next.js 16.3.8, sharp 0.35.5, DOMPurify 3.4.16, Moment
2.31.0, Vue 3.5.42, and the Angular 21.2.24 family. Angular and Vue packages
move together to satisfy their exact-version peers.
HTTP security updates pin Axios 1.20.0, Undici 6.28.1 and 7.29.1 in their
existing major families, Hono 4.13.7, fast-uri 3.1.8, qs 6.16.0, engine.io
6.6.10, proxy-addr 2.0.8, ip-address 10.7.1, MCP SDK 1.31.0, AI SDK provider
utilities 4.0.33, and http-cache-semantics 4.3.0. The latter is outside the
advisory range (through 4.2.0), although GitHub does not list a first patched
version.
Database instrumentation security updates pin the patched Cassandra, Knex,
Mongoose, MySQL, MySQL2, OracleDB, PostgreSQL, and Tedious OpenTelemetry
packages together to prevent unconditional database-user attributes in spans.
Two fixes require major-version upgrades: Faker 9.9.0 to 10.5.0 and
postcss-selector-parser 6.0.10 to 7.1.6. Faker 10 requires a recent Node 20/22
or Node 24+, satisfied by the Node 26 image; the upstream Login source already
uses modern Faker APIs. Review these separately from the patch/minor updates.
The build omits `node-forge` and its types, which are used only by upstream
`dockerized/ca/utils/tls.ts`. Dockerized integration fixtures are excluded from
production TypeScript checking; all runtime source stays strictly checked, and
the bounded-retry regressions still run. The committed lockfile removes both
packages from the dependency graph rather than dismissing the alert.

CI publishes immutable `v4.19.4-idp-retry1-<commit>` tags after native ARM64
build, runtime vulnerability scanning, and smoke tests. It does not overwrite
the existing fixed `v4.19.4-idp-retry1` release tag.
Deployment is separate: only update the Fleet values after this build succeeds.
Rollback to upstream `ghcr.io/zitadel/zitadel-login:v4.19.4` removes the retry
protection; retain the custom image digest for a subsequent rollback.
There is no database migration or change to identity-linking authorization.

An affected user whose account and GitHub link were already created should start
a fresh GitHub sign-in from the application; do not delete/recreate their account.

The production TypeScript project excludes test fixtures (which predate the
patched Next.js compiler); strict checking remains enabled for all runtime
source. Vitest runs the bounded-retry regressions separately in the image build.

Login v4.19.4 signs session cookies. Configure `ZITADEL_SESSION_COOKIE_SECRET`
from the same SOPS-managed secret on every replica. Existing unsigned Login UI
cookies are rejected once after upgrade; application sessions and issued tokens
are unaffected. The core upgrade runs database setup migrations, so a core
downgrade requires a separate database compatibility review.

As of 2026-10-15, [braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
and [sprintf-js](https://github.com/advisories/GHSA-hp3w-g68c-fv3c) have no patched
release. They remain in development tooling and their alerts stay open until
upstream fixes or reviewed replacements are available. The published Login
runtime SBOM contains neither package.
