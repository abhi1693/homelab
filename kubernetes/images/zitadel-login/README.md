# Zitadel Login registration repair

This image builds Zitadel Login v4.15.3 from commit
`e2886a61670ca8fd41c9434f87036546e5620bcc` with one source patch: after
successful user creation and identity-provider linking, retry session creation
on `NotFound` after 500 ms, 1 s, and 2 s. User creation and identity linking are
never retried. Permission, authentication, and all other errors propagate.

The upstream password registration retry (zitadel/zitadel#12189) does not cover
`registerUserAndLinkToIDP`. On 2026-09-14 production created an account and its
GitHub link successfully, but the immediate session lookup returned
`QUERY-Dfbg2`; resubmitting registration then returned `V3-DKcYh` (duplicate).
Both user lookup APIs subsequently returned the active account.

The Docker build checks the patch anchors, compiles the upstream application,
and runs focused recovery, rejection, and exhaustion tests before publication.
The runtime retains the upstream entrypoint, certificate handling, and user.
It uses a refreshed Node 24 Alpine base, with package managers removed from the
runtime. The committed pnpm lockfile pins patched Next.js, gRPC, telemetry,
archive, and HTTP dependencies required by the runtime security scan.
Deployment is separate: only update the Fleet values after this build succeeds.
Rollback restores the upstream `ghcr.io/zitadel/zitadel-login:v4.15.3` image.
There is no database migration or change to identity-linking authorization.

An affected user whose account and GitHub link were already created should start
a fresh GitHub sign-in from the application; do not delete/recreate their account.

The production TypeScript project excludes test fixtures (which predate the
patched Next.js compiler); strict checking remains enabled for all runtime
source. Vitest runs the bounded-retry regressions separately in the image build.
