# Public mirror security

`abhi1693/home-lab` is the private source of truth. `abhi1693/homelab` is a
sanitized public snapshot repository, not a clone of the private Git history.
Never push the private repository's branches, tags, or objects to the public
remote.

The publisher lives in `.github/workflows/mirror-public.yml`; its exporter,
requirements, and regression fixtures remain private under `.github/`.

## Publication boundary

- Read regular, tracked text blobs from the selected immutable source commit.
  Local changes, ignored files, symlinks, and submodules are not publication
  inputs. Reject unreadable, ambiguous, or undecodable inputs.
- Omit private inventories, network configuration, GitHub metadata, credential
  files, SOPS artifacts, certificate/key material, and actual Secret/ConfigMap
  resources, including embedded resources and placeholder Secret templates.
  Unrendered Helm generators are omitted rather than exempted from parsing.
  Declarative references to those
  resource kinds do not contain the resource payload and may remain public.
- Remove credential-derived fingerprint annotations from exported manifests.
  Keep the private manifests unchanged.
- Rebuild the public checkout from the validated staging tree, removing stale
  exclusions while preserving Git metadata and the public repository's existing
  `.github/FUNDING.yml` byte for byte. Validate funding like every other exported
  file; preservation is not a scanning exception.
- Require the checksum-pinned Gitleaks scanner to pass before changing the
  public checkout. Scan with built-in rules, recursive decoding/archive
  inspection, and no repository-controlled configuration, baseline, inline
  exemption, or ignore file. Never print scanner findings or parser input.
- Inspect the public repository's full reachable history before publishing.
  A clean current tree does not excuse certificates, secrets, or encrypted
  artifacts retained in parent commits or another advertised ref. Stop on a
  history finding; routine publication must never rewrite history automatically.
- Publish only from the private repository's default branch on the scheduled or
  manual workflow. Serialize all publishers for the public target. Make the
  write credential available only to the final push step through ephemeral
  authentication; never put it in a remote URL.

The public repository is intentionally incomplete and cannot independently
bootstrap the private cluster. Keep the existing public funding file; do not
replace it with a source-side copy.

Credential-shaped schema definitions and code/documentation examples may also
be omitted conservatively. An export-policy exclusion alone is not evidence
that a real credential was exposed.

## Validation

The infrastructure regression workflow runs the publisher's negative fixtures
when its workflow, exporter, tests, or requirements change. Run them from a
Python virtual environment with the same pinned dependencies:

```sh
python3 -m pip install --requirement .github/requirements/public-mirror.txt
PUBLIC_MIRROR_GITLEAKS=/absolute/path/to/verified/gitleaks \
  python3 -m unittest discover -s .github/tests -p 'test_public_mirror.py'
```

Use the checksum-verified scanner version pinned in the workflow. The scanner
environment variable makes the real credential/history integration cases
mandatory locally, as they are in CI. Audit a full public clone without changing
its files or refs:

```sh
python3 .github/scripts/public_mirror.py \
  --audit-history /absolute/path/to/full-public-clone \
  --gitleaks /absolute/path/to/verified/gitleaks
```

Before publication, the publisher also exports the actual source commit and
runs the real scanner over the complete candidate, including the funding file.
A failed gate must stop publication. Fix the policy or offending source input;
do not add a baseline or an exemption to make the run pass.

GitHub secret scanning and push protection provide additional detection on the
public repository. They do not replace the export policy or certificate checks.

## If material reaches public history

1. Identify the exact public repository, all advertised branches/tags, and every
   historical path or renamed copy. Scan reachable blobs and commit/tag messages
   with redacted output. Distinguish actual credentials, encrypted artifacts,
   public certificates, and references before deciding what to remove.
2. Revoke or rotate actual exposed credentials first. A public CA certificate
   alone does not imply its private key was exposed. Keep evidence and any
   recovery backup local with restricted permissions; never create a public
   backup ref that preserves the material.
3. Fix and validate the publisher before resuming publication. In a separate
   fresh clone of the **public repository only**, use `git-filter-repo` with
   sensitive-data-removal support to remove all affected paths/content from all
   writable refs. Preserve unrelated content and funding. Never rewrite the
   private GitOps source history as part of mirror cleanup.
4. Scan the entire rewritten candidate. Verify remote refs have not changed,
   then update only the reviewed refs using explicit force-with-lease checks.
   Fresh-clone the public remote and repeat both history and current-tree scans;
   verify subsequent normal publication still passes.
5. Record changed refs and the first changed commits. Existing clones, forks,
   cached views, and GitHub's read-only pull-request refs are outside a branch
   rewrite. Follow GitHub's sensitive-data-removal process for platform cleanup
   and coordinate separately with owners of retained copies when authorized.

See [GitHub's removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
and the [official git-filter-repo documentation](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt).
