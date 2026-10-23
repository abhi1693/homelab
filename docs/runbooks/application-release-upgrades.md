# Sequential application releases

Upgrade one application cohort through source CI, immutable image publication,
Git and Fleet, then verify its live behavior before starting another cohort.
Coupled containers, init containers and release hooks belong to that same
cohort even when they run in another application's pod.

Before creating a release tag:

1. Record active and paused workloads, runtime versions, public responses,
   Fleet state, database/storage health and recent successful backups. Review
   migration and persistent-state compatibility with the deployed release.
2. Validate the complete release manifest and version authority against the
   actual released shared workflow. PR and release runner selections must both
   have available capacity; use the shared native GitHub-hosted ARM64 default
   unless a registered alternative has been verified.
3. Check each GHCR package's source-repository association, private/public
   visibility and Actions access. A PR build with publication disabled proves
   neither registry write permission nor release-runner availability. Existing
   private packages can retain explicit access rules after being linked: the
   source label alone does not establish Actions write access. Configure the
   package's Manage Actions access or use a repository-owned package created by
   its normal workflow token. Preserve required visibility and rollback images;
   do not add a broad owner publishing token to work around package permissions.
4. Check artifact-attestation support for the source repository's visibility and
   account plan. GitHub artifact attestations for user-owned private repositories
   require an eligible enterprise plan. Preserve required privacy. For that
   unsupported capability, set the shared release workflow's `attest: false`
   explicitly, document the limitation, and verify embedded BuildKit provenance
   and exact release reports. Do not claim a signed GitHub attestation. Keep
   signed GitHub attestations enabled and verified where they are supported.
5. Require the final source's tests and native runtime image gates: recognized
   OS/package coverage, SBOM, strict HIGH/CRITICAL and secret scans, and actual
   application/native-library smoke checks. Preserve required runtime tools and
   use isolated fixtures for writes or external integrations. Document narrowly
   verified public test-fixture false positives; keep vulnerability gates active.
   Review every Fleet container command, init container and release hook against
   the candidate image, including build, archive/restore and migration tools.
   Exercise the actual flags and file/permission contracts in native smoke;
   checking only the default application entrypoint does not cover those tools.

After source merge and successful merged CI, publish from the exact validated
commit. A release event starts the build; it does not establish image readiness.
Wait for the complete cohort's normal workflow-token publication, native scans,
smoke tests, supported attestations and final immutable promotion. If publication fails,
retain the source tag and record the blocked release. Correct source changes
move forward in a new patch version; never move an existing tag.

Verify the promoted registry index, ARM64 child manifest and configuration
against the release reports. Trivy's `Metadata.ImageID` identifies the image
configuration; `ArtifactID` is not a substitute. Verify provenance subject,
source revision and run. Where GitHub artifact attestations are supported,
cryptographically verify the expected source ref and reusable signer workflow.
Embedded BuildKit provenance alone does not provide that separate signature. Keep credentials in the intended service's
authentication path and exclude them from logs, artifacts and source commits.

Update the entire cohort's tag/digest pins, release hooks and required build
commands together. Image automation must follow published container tags and
digests, with appropriate cohort grouping and compatibility bounds. Run the
repository checks and server-side dry runs, commit and push, then let Fleet
reconcile. Keep unrelated changes and paused replica/schedule settings intact.

Accept the rollout only after Fleet desired/applied IDs match, replacement pods
remain ready without unexpected restarts, and live image/runtime versions and
application checks agree. Check API/frontend hooks, database revision and state
preservation where applicable. Compare public probes using the same client
headers as the baseline: an edge denial can be the intended result for an
unpublished route. Use isolated fixtures for synthetic signed or mutating
requests, and ordinary traffic for production integrations. Record the evidence
and any remaining compatibility holds before moving to the next application.
