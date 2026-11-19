# Official SonarQube MCP qualification

The `SonarQube MCP image qualification` workflow tests the exact proposed
upstream OCI digest on a native ARM64 runner before its Fleet image pin changes.
It builds no application image and uses no production token or cluster access.

`smoke.sh` requires Java 21.0.13 and Node 24.22.1 within their reviewed majors,
checks the effective default JVM and Node trust stores against the inventory's
two distrusted CA fingerprints, and verifies non-root, read-only startup,
health/info routes and rejection of an unauthenticated MCP request. All runtime
tests use isolated Docker networks with no external connectivity.

The Java helper compiles to Java 17 bytecode with the runner's JDK so the
candidate's trimmed JRE can execute it without adding a compiler to the image.
Container scanning is a separate gate; shaded JAR dependencies must also be
assessed from upstream's exact ARM64 SBOM because package metadata may be absent.
Only update the deployed image after these qualification gates pass. Successful
isolated checks do not replace Fleet convergence and authenticated live proof.
