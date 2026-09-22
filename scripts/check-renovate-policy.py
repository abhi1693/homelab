#!/usr/bin/env python3
"""Enforce the repository's Renovate coverage and critical-dependency boundary."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("kubernetes/projects/applications/apps/renovate/configmap.yaml")

CRITICAL_PATHS = (
    Path("infrastructure/ansible/inventories/home/group_vars"),
    Path("kubernetes/projects/database/apps/cnpg-operator/chart"),
    Path("kubernetes/projects/system/apps/csi-driver-nfs"),
    Path("kubernetes/projects/system/apps/longhorn-fstrim-labeler"),
    Path("kubernetes/projects/system/apps/metallb"),
    Path("kubernetes/projects/system/apps/sops-secrets-operator"),
)

CRITICAL_GLOBS = (
    "kubernetes/projects/system/apps/rancher-*",
)

REQUIRED_IGNORE_PATHS = (
    "infrastructure/ansible/inventories/home/group_vars/**",
    "kubernetes/projects/database/apps/cnpg-operator/chart/**",
    "kubernetes/projects/database/apps/valkey/helmop.yaml",
    "kubernetes/projects/home-automation/apps/rack-ops-controllers/secret-bootstrap.yaml",
    "kubernetes/projects/system/apps/csi-driver-nfs/**",
    "kubernetes/projects/system/apps/longhorn-fstrim-labeler/**",
    "kubernetes/projects/system/apps/metallb/**",
    "kubernetes/projects/system/apps/rancher-*/**",
    "kubernetes/projects/system/apps/sops-secrets-operator/**",
)

FORBIDDEN_DEPENDENCIES = (
    "cilium/cilium",
    "cilium/cilium-cli",
    "jetstack/cert-manager",
    "k3s-io/k3s",
    "kube-vip/kube-vip",
    "kubernetes-csi/csi-driver-nfs",
    "longhorn/longhorn",
    "metallb/metallb",
    "rancher/rancher",
    "rancher/mirrored-coredns-coredns",
    "rancher/mirrored-metrics-server",
    "registry.k8s.io/sig-storage/nfsplugin",
)


def iter_files(path: Path):
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from (candidate for candidate in path.rglob("*") if candidate.is_file())


def main() -> int:
    failures: list[str] = []
    config = (REPOSITORY_ROOT / CONFIG_PATH).read_text(encoding="utf-8")

    # Exercise the configured matcher: a greedy repository capture once let
    # Renovate replace an image digest with a GitHub release tag.
    image_matchers = [
        json.loads(line.strip().rstrip(","))
        for line in config.splitlines()
        if "(?:image|imageName)" in line and "(?<currentDigest>sha256:" in line
    ]
    if len(image_matchers) != 1:
        failures.append("expected exactly one tag-and-digest image matcher")
    else:
        matcher = re.compile(re.sub(r"\(\?<([A-Za-z]+)>", r"(?P<\1>", image_matchers[0]))
        digest = "sha256:" + "a" * 64
        for repository in ("registry.home/ghcr.io/example/app", "registry.home:5000/example/app"):
            for key in ("image", "imageName"):
                for quote in ("", '"', "'"):
                    for suffix in ("", "@" + digest):
                        sample = (
                            "# renovate: datasource=github-releases depName=example/app\n"
                            f"  {key}: {quote}{repository}:0.0.8{suffix}{quote}\n"
                        )
                        match = matcher.search(sample)
                        if (
                            match is None
                            or match.group("currentValue") != "0.0.8"
                            or match.group("currentDigest") != (digest if suffix else None)
                        ):
                            failures.append(f"Renovate image matcher misreads {sample!r}")

    devfeed_rules = [
        block
        for block in re.findall(r"\{[^{}]*\}", config)
        if 'groupSlug: "devfeed-images"' in block
    ]
    if len(devfeed_rules) != 1:
        failures.append("expected one grouped DevFeed Docker image rule")
    else:
        rule = devfeed_rules[0]
        for required in (
            'matchDatasources: ["docker"]',
            'enabled: true',
            'versioning: "semver"',
            'ignoreUnstable: true',
            'pinDigests: true',
        ):
            if required not in rule:
                failures.append(f"DevFeed image rule requires {required}")
        allowed = re.search(r'allowedVersions:\s*("[^"\n]+")', rule)
        if allowed is None:
            failures.append("DevFeed image rule needs a stable-tag filter")
        else:
            pattern = json.loads(allowed.group(1)).strip("/")
            for tag in ("0.0.38", "1.2.3", "10.20.30"):
                if not re.fullmatch(pattern, tag):
                    failures.append(f"DevFeed release tag rejected: {tag}")
            for tag in (
                "latest", "master", "v0.0.38", "0.0.38-rc.1", "0.0.38+build.1",
                "01.2.3", "1.2", "1.2.3.4", "a" * 40, "1" * 40,
            ):
                if re.fullmatch(pattern, tag):
                    failures.append(f"DevFeed non-release tag allowed: {tag}")

        devfeed_path = REPOSITORY_ROOT / "kubernetes/projects/applications/apps/devfeed"
        for path in devfeed_path.glob("*.yaml"):
            contents = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r"(?m)^\s*image:\s*registry.home/(ghcr.io/abhi1693/devfeed.tech/[^:\s]+):",
                contents,
            ):
                package = match.group(1)
                preceding = contents[:match.start()].rstrip().splitlines()[-1].strip()
                if preceding != f"# renovate: datasource=docker depName={package}":
                    failures.append(f"DevFeed image has incorrect Docker metadata: {path.name}")
                if f'"{package}"' not in rule:
                    failures.append(f"DevFeed image missing from grouped rule: {package}")

    required_merge_policy = {
        "automerge": "true",
        "automergeType": '"branch"',
        "platformAutomerge": "false",
        "prCreation": '"immediate"',
        "dependencyDashboard": "false",
        "recreateWhen": '"always"',
    }
    for key, expected in required_merge_policy.items():
        values = re.findall(rf"^\s*{key}:\s*([^,\n]+)", config, re.MULTILINE)
        if not values or any(value.strip() != expected for value in values):
            failures.append(f"Renovate direct-update policy requires {key}: {expected}")

    for required_path in REQUIRED_IGNORE_PATHS:
        quoted_path = f'"{required_path}"'
        if quoted_path not in config:
            failures.append(f"Renovate ignorePaths is missing {required_path}")

    for dependency in FORBIDDEN_DEPENDENCIES:
        if dependency in config:
            failures.append(f"critical dependency is present in Renovate config: {dependency}")

    critical_roots = [REPOSITORY_ROOT / path for path in CRITICAL_PATHS]
    for pattern in CRITICAL_GLOBS:
        critical_roots.extend(REPOSITORY_ROOT.glob(pattern))

    for root in critical_roots:
        for path in iter_files(root):
            try:
                contents = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "renovate:" in contents.lower():
                failures.append(
                    f"critical path contains Renovate metadata: {path.relative_to(REPOSITORY_ROOT)}"
                )

    image_pattern = re.compile(
        r"^\s*(?:-\s*)?(?:image|imageName):\s*(?![<{])\S+:[^/\s]+"
    )
    tag_pattern = re.compile(r'^\s*tag:\s*["\']?[vV]?\d')
    version_pattern = re.compile(r'^\s*version:\s*["\']?[vV]?\d')

    for path in (REPOSITORY_ROOT / "kubernetes/projects").rglob("*.yaml"):
        if "secrets.sops" in path.name:
            continue
        if any(path.is_relative_to(root) for root in critical_roots):
            continue

        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if image_pattern.match(line) and "@sha256:" in line:
                pin = line.split("@sha256:", 1)[1].split()[0].rstrip("\"'")
                if not re.fullmatch(r"[a-f0-9]{64}", pin):
                    failures.append(
                        f"invalid SHA-256 image pin: {path.relative_to(REPOSITORY_ROOT)}:{index + 1}"
                    )
            requires_marker = image_pattern.match(line) or tag_pattern.match(line)
            if path.name.startswith("helmop") or path.name == "fleet.yaml":
                requires_marker = requires_marker or version_pattern.match(line)
            if not requires_marker:
                continue
            preceding_lines = lines[max(0, index - 2) : index]
            if not any("renovate:" in candidate.lower() for candidate in preceding_lines):
                relative_path = path.relative_to(REPOSITORY_ROOT)
                failures.append(
                    f"non-critical dependency lacks Renovate metadata: "
                    f"{relative_path}:{index + 1}"
                )

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    print("Renovate policy check passed; critical dependencies remain manual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
