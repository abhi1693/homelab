#!/usr/bin/env python3
"""Enforce the repository's Renovate coverage and critical-dependency boundary."""

from __future__ import annotations

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
