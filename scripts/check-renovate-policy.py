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
    Path("kubernetes/projects/system/apps/cilium"),
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
    "kubernetes/projects/system/apps/cilium/**",
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


REGISTRY_TRACKED_IMAGES = {
    "kubernetes/projects/applications/apps/personal-blog/deployment.yaml": "ghcr.io/abhi1693/personal-blog",
    "kubernetes/projects/applications/apps/portfolio/deployment.yaml": "ghcr.io/abhi1693/portfolio",
    "kubernetes/projects/applications/apps/wardn-ai-website/deployment.yaml": "ghcr.io/abhi1693/wardn-ai-website",
    "kubernetes/projects/applications/apps/wardn-hub/deployment-scoring.yaml": "ghcr.io/abhi1693/wardn-hub-scoring/runtime",
    "kubernetes/projects/home-automation/apps/home-assistant-mobile-webhook/deployment.yaml": "ghcr.io/abhi1693/ha-sensors-gateway",
}


HUB_COHORT = {
    "deployment-api.yaml": ("backend", "backend"),
    "deployment-codex-app-server.yaml": ("codex-app-server",),
    "deployment-frontend.yaml": ("backend", "frontend", "frontend"),
    "deployment-scoring.yaml": ("backend",),
    "deployment-worker.yaml": ("backend", "backend"),
    "find-skills-refresh-job.yaml": ("backend", "backend"),
    "next-build-cleanup-cronjob.yaml": ("frontend",),
    "next-builder-job.yaml": ("backend", "frontend"),
}


def check_hub_image_cohort(app: Path) -> list[str]:
    """Reject partial version/digest updates across coupled Hub containers."""
    failures: list[str] = []
    versions: set[str] = set()
    digests: dict[str, set[str]] = {}
    image_line = re.compile(
        r"^\s*image:\s*(?P<quote>[\"']?)(?P<reference>[^\s\"']+)"
        r"(?P=quote)\s*(?:#.*)?$"
    )
    component_pattern = re.compile(
        r"(?:^|/)wardn-hub-(backend|frontend|codex-app-server)(?=[:@]|$)"
    )
    canonical = re.compile(
        r"registry\.home/(ghcr\.io/abhi1693/wardn-hub-"
        r"(?:backend|frontend|codex-app-server)):(.+)"
    )
    found_by_file: dict[str, list[str]] = {}
    paths = set(app.rglob("*.yaml")) | set(app.rglob("*.yml"))
    for path in sorted(paths):
        name = str(path.relative_to(app))
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = image_line.fullmatch(line)
            component = component_pattern.search(match["reference"]) if match else None
            if component is None:
                continue
            found_by_file.setdefault(name, []).append(component[1])
            if name not in HUB_COHORT:
                failures.append(f"Hub image outside reviewed cohort coverage: {name}:{index + 1}")
            selected = canonical.fullmatch(match["reference"])
            if selected is None:
                failures.append(f"Hub cohort must use its canonical Harbor image: {name}:{index + 1}")
                continue
            package, selection = selected.groups()
            marker = f"# renovate: datasource=docker depName={package}"
            if index == 0 or lines[index - 1].strip() != marker:
                failures.append(f"Hub cohort Docker metadata missing: {name}:{index + 1}")
            pin = re.fullmatch(r"(\d+\.\d+\.\d+)@(sha256:[a-f0-9]{64})", selection)
            if pin is None:
                failures.append(f"Hub cohort needs a stable tag and digest: {name}:{index + 1}")
                continue
            versions.add(pin[1])
            digests.setdefault(component[1], set()).add(pin[2])
    for name, expected in HUB_COHORT.items():
        if sorted(found_by_file.get(name, [])) != sorted(expected):
            failures.append(f"Hub cohort containers changed without coverage review: {name}")
    if len(versions) != 1:
        failures.append("Hub cohort must have one application version across all 14 image references")
    if set(digests) != {"backend", "frontend", "codex-app-server"} or any(
        len(values) != 1 for values in digests.values()
    ):
        failures.append("Hub cohort must have one immutable digest per component")
    return failures


def iter_files(path: Path):
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from (candidate for candidate in path.rglob("*") if candidate.is_file())


def check_default_merge_policy(
    config: str, reviewed_cohort_rule: str | None, *additional_reviewed_rules: str
) -> list[str]:
    """Keep direct updates enabled outside the explicitly reviewed image cohorts."""
    defaults = config
    for rule in (reviewed_cohort_rule, *additional_reviewed_rules):
        if rule:
            defaults = defaults.replace(rule, "", 1)
    required = {
        "automerge": "true", "automergeType": '"branch"',
        "platformAutomerge": "false", "prCreation": '"immediate"',
        "dependencyDashboard": "false", "recreateWhen": '"always"',
    }
    failures = []
    for key, expected in required.items():
        values = re.findall(rf"^\s*{key}:\s*([^,\n]+)", defaults, re.MULTILINE)
        if not values or any(value.strip() != expected for value in values):
            failures.append(f"Renovate direct-update policy requires {key}: {expected}")
    return failures


def check_license_image_policy(config: str, app: Path) -> list[str]:
    """Track both published packages without changing existing image selections."""
    failures: list[str] = []
    packages = [
        "ghcr.io/abhi1693/wardn-license-server-backend",
        "ghcr.io/abhi1693/wardn-license-server-frontend",
    ]
    rules = [block for block in re.findall(r"\{[^{}]*\}", config)
             if 'groupSlug: "wardn-license-server-images"' in block]
    if len(rules) != 1:
        failures.append("expected one reviewed Wardn License Server Docker rule")
    else:
        rule = rules[0]
        for required in (
            'matchDatasources: ["docker"]', 'enabled: true',
            'versioning: "semver"', 'allowedVersions: ">=0.1.2 <0.2.0"',
            'ignoreUnstable: true', 'pinDigests: true', 'groupSingleUpdates: true',
        ):
            if required not in rule:
                failures.append(f"License published-image rule requires {required}")
        selected = re.search(r"matchPackageNames:\s*(\[[^\]]*\])", rule)
        try:
            selected_packages = json.loads(selected[1]) if selected else None
        except json.JSONDecodeError:
            selected_packages = None
        if selected_packages is None or sorted(selected_packages) != packages:
            failures.append("License reviewed rule must contain exactly backend/frontend packages")
        if re.findall(r"^\s*automerge:\s*([^,\n]+)", rule, re.MULTILINE) != ["false"]:
            failures.append("License reviewed cohort must disable automerge exactly once")
    for path in app.rglob("*.yaml"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            image = re.fullmatch(
                r"\s*image:\s*[\"']?registry\.home/(ghcr\.io/abhi1693/"
                r"wardn-license-server-(?:backend|frontend)):[^\s\"']+[\"']?\s*(?:#.*)?",
                line,
            )
            if image and (index == 0 or lines[index - 1].strip() !=
                          f"# renovate: datasource=docker depName={image[1]}"):
                failures.append(f"License image must track its published Docker package: {path.name}:{index + 1}")
        if "datasource=github-releases depName=abhi1693/wardn-license-server" in "\n".join(lines):
            failures.append(f"License source releases cannot authorize image updates: {path.name}")
    return failures


LICENSE_COHORT = {
    "deployment.yaml": (("api", "backend"), ("frontend", "frontend")),
    "migration-job.yaml": (("migrate", "backend"),),
}


def check_license_image_cohort(app: Path) -> list[str]:
    """Require complete immutable API/frontend/direct-writer hook updates."""
    failures: list[str] = []
    versions: set[str] = set()
    digests: dict[str, set[str]] = {}
    found_by_file: dict[str, list[tuple[str, str]]] = {}
    image_line = re.compile(
        r"^\s*image:\s*(?P<quote>[\"']?)(?P<reference>[^\s\"']+)"
        r"(?P=quote)\s*(?:#.*)?$"
    )
    component_pattern = re.compile(
        r"(?:^|/)wardn-license-server-(backend|frontend)(?=[:@]|$)"
    )
    canonical = re.compile(
        r"registry\.home/(ghcr\.io/abhi1693/wardn-license-server-"
        r"(?:backend|frontend)):(.+)"
    )
    paths = set(app.rglob("*.yaml")) | set(app.rglob("*.yml"))
    for path in sorted(paths):
        name = str(path.relative_to(app))
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            image = image_line.fullmatch(line)
            component = component_pattern.search(image["reference"]) if image else None
            if component is None:
                continue
            indent = len(line) - len(line.lstrip())
            container = ""
            for prior in reversed(lines[:index]):
                if not prior.strip() or prior.lstrip().startswith("#"):
                    continue
                prior_indent = len(prior) - len(prior.lstrip())
                if prior_indent == indent - 2:
                    header = re.fullmatch(r"\s*- name:\s*[\"']?([a-z0-9-]+)[\"']?\s*", prior)
                    if header:
                        container = header[1]
                    break
                if prior_indent < indent - 2:
                    break
            found_by_file.setdefault(name, []).append((container, component[1]))
            if name not in LICENSE_COHORT:
                failures.append(f"License image outside reviewed cohort: {name}:{index + 1}")
            selected = canonical.fullmatch(image["reference"])
            if selected is None:
                failures.append(f"License cohort needs its canonical Harbor image: {name}:{index + 1}")
                continue
            package, selection = selected.groups()
            if index == 0 or lines[index - 1].strip() != f"# renovate: datasource=docker depName={package}":
                failures.append(f"License cohort Docker metadata missing: {name}:{index + 1}")
            pin = re.fullmatch(r"((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))@(sha256:[a-f0-9]{64})", selection)
            if pin is None:
                failures.append(f"License cohort needs a stable tag and digest: {name}:{index + 1}")
                continue
            versions.add(pin[1])
            digests.setdefault(component[1], set()).add(pin[2])
    for name, expected in LICENSE_COHORT.items():
        if sorted(found_by_file.get(name, [])) != sorted(expected):
            failures.append(f"License cohort containers changed without coverage review: {name}")
    if len(versions) != 1:
        failures.append("License cohort must have one version across API, frontend and migration hook")
    if set(digests) != {"backend", "frontend"} or any(len(values) != 1 for values in digests.values()):
        failures.append("License cohort must have one immutable digest per component")
    return failures



BACKUP_WRITER_PACKAGES = (
    "ghcr.io/abhi1693/qbittorrent-smart-queues",
    "ghcr.io/abhi1693/ryokan",
    "ghcr.io/abhi1693/k8s-recommendation-engine",
    "ghcr.io/abhi1693/rack-ops",
)
BACKUP_WRITER_RULE = "Require passing restore-point cohort checks before writer image automerge"
TERRAFORM_RULE = "Require initialized template validation before Terraform automerge"
TERRAFORM_CI_PATHS = {
    "coder/templates/**/*.tf",
    "coder/templates/**/.terraform.lock.hcl",
    "scripts/run-pre-commit-validation.sh",
    "scripts/check-renovate-policy.py",
    "scripts/check-terraform-toolchain.py",
    "scripts/tests/test_terraform_toolchain.py",
    "scripts/tests/test_terraform_merge_policy.py",
    "kubernetes/projects/applications/apps/renovate/configmap.yaml",
    ".github/workflows/terraform-validation.yml",
}


def check_terraform_merge_policy(config: str, workflow: str, runner: str) -> list[str]:
    """Require initialized validation on the actual Terraform update branch."""
    failures: list[str] = []
    package_rules = config.split("packageRules:", 1)[-1].split("lockFileMaintenance:", 1)[0]
    rules = re.findall(r"\{[^{}]*\}", package_rules)
    selected = [rule for rule in rules if f'description: "{TERRAFORM_RULE}"' in rule]
    if len(selected) != 1:
        failures.append("expected one exact Coder Terraform test gate")
    else:
        rule = selected[0]
        required = ('matchManagers: ["terraform"]',
                    'matchFileNames: ["coder/templates/**"]', 'ignoreTests: false')
        keys = re.findall(r"^\s*(\w+):", rule, re.MULTILINE)
        if (any(value not in rule for value in required)
                or sorted(keys) != ["description", "ignoreTests", "matchFileNames", "matchManagers"]):
            failures.append("Terraform gate must require tests for exactly the Coder Terraform manager scope")
        if len(rules) < 3 or rules[-3] != rule:
            failures.append("Terraform gate must precede only the writer gate and final manual helper rule")

    for event in ("pull_request", "push"):
        section = re.search(rf"^  {event}:\n(.*?)(?=^  [a-z_]+:|^\S|\Z)",
                            workflow, re.MULTILINE | re.DOTALL)
        paths = re.search(r"^    paths:\n((?:      - [^\n]+\n)+)",
                          section[1], re.MULTILINE) if section else None
        selected_paths = [line.strip()[2:].strip('\"\'') for line in paths[1].splitlines()] if paths else []
        if set(selected_paths) != TERRAFORM_CI_PATHS or len(selected_paths) != len(TERRAFORM_CI_PATHS):
            failures.append(f"Terraform CI must watch its exact template and validation inputs on {event}")
        if event == "push":
            branches = re.search(r"^    branches:\n((?:      - [^\n]+\n)+)",
                                 section[1], re.MULTILINE) if section else None
            selected_branches = [line.strip()[2:].strip('\"\'') for line in branches[1].splitlines()] if branches else []
            if sorted(selected_branches) != ["master", "renovate/**"]:
                failures.append("Terraform CI must run on master and renovate/** pushes")
    for command in ("terraform", "renovate-policy"):
        if not re.search(rf"^\s+run: scripts/run-pre-commit-validation\.sh {command}$",
                         workflow, re.MULTILINE):
            failures.append("Terraform CI must execute full template and automerge policy validation")
    toolchain_command = "python3 scripts/check-terraform-toolchain.py --expected-platform linux_arm64"
    if (len(re.findall(r"^\s+run: " + re.escape(toolchain_command) + r"$", workflow, re.MULTILINE)) != 1
            or not workflow.find("uses: hashicorp/setup-terraform@") < workflow.find("run: " + toolchain_command)
            < workflow.find("run: scripts/run-pre-commit-validation.sh terraform")):
        failures.append("Terraform CI must verify the actual native ARM64 binary and embedded Go before initialization")
    cli_version = re.search(r'^\s+terraform_version: "(\d+)\.(\d+)\.(\d+)"$', workflow, re.MULTILINE)
    if (re.search(r"^\s*(?:if|continue-on-error):", workflow, re.MULTILINE)
            or not re.search(r"uses: hashicorp/setup-terraform@[a-f0-9]{40}\b", workflow)
            or cli_version is None or tuple(map(int, cli_version.groups())) < (1, 17, 0)):
        failures.append("Terraform CI needs an unconditional job with pinned setup action and CLI")
    function = re.search(r"^validate_terraform\(\) \{\n(.*?)^\}", runner,
                         re.MULTILINE | re.DOTALL)
    body = function[1] if function else ""
    commands = ("terraform fmt -check -recursive coder/templates",
                'terraform -chdir="${template}" init -backend=false -input=false',
                'terraform -chdir="${template}" validate')
    lines = [line.strip() for line in body.splitlines()]
    if (any(lines.count(command) != 1 for command in commands)
            or not all(body.find(a) < body.find(b) for a, b in zip(commands, commands[1:]))):
        failures.append("Terraform hook must format, initialize pinned modules without a backend, then validate")
    return failures


def check_backup_writer_merge_policy(config: str, workflow: str) -> list[str]:
    """Keep writer automerge enabled, gated by checks on its actual update branch."""
    failures = []
    package_rules = config.split("packageRules:", 1)[-1].split("lockFileMaintenance:", 1)[0]
    rules = re.findall(r"\{[^{}]*\}", package_rules)
    selected = [rule for rule in rules if f'description: "{BACKUP_WRITER_RULE}"' in rule]
    if len(selected) != 1:
        failures.append("expected one exact backup writer test gate")
    else:
        rule = selected[0]
        names = re.search(r"matchPackageNames:\s*(\[[^\]]*\])", rule)
        try:
            packages = json.loads(names[1]) if names else None
        except json.JSONDecodeError:
            packages = None
        if packages is None or sorted(packages) != sorted(BACKUP_WRITER_PACKAGES):
            failures.append("backup writer test gate must select exactly four Docker packages")
        if 'matchDatasources: ["docker"]' not in rule or re.findall(
                r"^\s*ignoreTests:\s*([^,\n]+)", rule, re.MULTILINE) != ["false"]:
            failures.append("backup writer image automerge must require passing tests")
        if len(rules) < 2 or rules[-2] != rule:
            failures.append("backup writer test gate must precede only the final manual helper rule")
    defaults = config.split("packageRules:", 1)[0]
    if re.findall(r"^\s*ignoreTests:\s*([^,\n]+)", defaults, re.MULTILINE) != ["true"]:
        failures.append("unrelated dependencies must retain the default ignoreTests policy")
    branches = re.search(r"^  push:\n    branches:\n((?:      - [^\n]+\n)+)", workflow, re.MULTILINE)
    selected_branches = [line.strip()[2:].strip('\"\'') for line in branches[1].splitlines()] if branches else []
    if sorted(selected_branches) != ["master", "renovate/**"]:
        failures.append("Infrastructure regressions must run on master and renovate/** pushes")
    for command in ["scripts/run-pre-commit-validation.sh kubernetes-tests",
                    "scripts/run-pre-commit-validation.sh renovate-policy"]:
        if f"run: {command}" not in workflow:
            failures.append("Renovate branches must execute app regressions and policy validation")
    for path in ["entertainment/apps/media-qbittorrent", "entertainment/apps/media-ryokan",
                 "entertainment/apps/media-state-backups", "home-automation/apps/cluster-ops",
                 "home-automation/apps/rack-ops-controllers"]:
        if workflow.count(f'"kubernetes/projects/{path}/**"') != 2:
            failures.append("writer and backup sources must trigger both PR and push regressions")
    return failures


def check_backup_helper_policy(config: str) -> list[str]:
    """The rolling backup interpreter needs explicit compatibility review."""
    package_rules = config.split("packageRules:", 1)[1].split("lockFileMaintenance:", 1)[0]
    rules = re.findall(r"\{[^{}]*\}", package_rules)
    selected = [rule for rule in rules if '"cgr.dev/chainguard/python"' in rule]
    if len(selected) != 1:
        return ["expected one manual backup helper image rule"]
    rule = selected[0]
    required = ('matchDatasources: ["docker"]',
                'matchPackageNames: ["cgr.dev/chainguard/python"]',
                "enabled: false")
    if any(value not in rule for value in required) or rules[-1] != rule:
        return ["backup helper updates must remain a final exact-package manual rule"]
    return []


def check_registry_tracked_images(config: str, root: Path) -> list[str]:
    """Require published-package metadata before source release publication."""
    failures: list[str] = []
    for location, package in REGISTRY_TRACKED_IMAGES.items():
        path = root / location
        app = path.parent.name
        contents = path.read_text(encoding="utf-8")
        marker = f"# renovate: datasource=docker depName={package}"
        if not re.search(
            rf"(?m)^\s*{re.escape(marker)}\n\s*image:\s*registry\.home/{re.escape(package)}:",
            contents,
        ):
            failures.append(f"{app} must track published Docker images and digests")
        enabled_rules = [
            block
            for block in re.findall(r"\{[^{}]*\}", config)
            if f'"{package}"' in block
            and 'matchDatasources: ["docker"]' in block
            and "enabled: true" in block
        ]
        if not enabled_rules:
            failures.append(f"{app} Docker updates need an explicit enabled package rule")

    for rule in re.findall(r"\{[^{}]*\}", config):
        if ('matchDatasources: ["github-releases"]' in rule
                and '"abhi1693/personal-blog"' in rule and "enabled: true" in rule):
            failures.append("personal-blog source release must not enable image updates")
    return failures


def main() -> int:
    failures: list[str] = []
    config = (REPOSITORY_ROOT / CONFIG_PATH).read_text(encoding="utf-8")
    failures.extend(check_backup_helper_policy(config))
    failures.extend(check_terraform_merge_policy(
        config, (REPOSITORY_ROOT / ".github/workflows/terraform-validation.yml").read_text(),
        (REPOSITORY_ROOT / "scripts/run-pre-commit-validation.sh").read_text(),
    ))
    failures.extend(check_backup_writer_merge_policy(
        config, (REPOSITORY_ROOT / ".github/workflows/infrastructure-regressions.yml").read_text()
    ))
    failures.extend(check_hub_image_cohort(
        REPOSITORY_ROOT / "kubernetes/projects/applications/apps/wardn-hub"
    ))
    hub_rules = [
        block for block in re.findall(r"\{[^{}]*\}", config)
        if 'groupSlug: "wardn-hub-images"' in block
    ]
    if len(hub_rules) != 1:
        failures.append("expected one reviewed Wardn Hub Docker cohort rule")
    else:
        for required in (
            'matchDatasources: ["docker"]', 'enabled: true',
            'versioning: "semver"', 'ignoreUnstable: true', 'pinDigests: true',
            'automerge: false',
            '"ghcr.io/abhi1693/wardn-hub-backend"',
            '"ghcr.io/abhi1693/wardn-hub-frontend"',
            '"ghcr.io/abhi1693/wardn-hub-codex-app-server"',
        ):
            if required not in hub_rules[0]:
                failures.append(f"Hub image cohort rule requires {required}")
        packages = re.search(r"matchPackageNames:\s*(\[[^\]]*\])", hub_rules[0])
        if packages is None or sorted(json.loads(packages[1])) != [
            "ghcr.io/abhi1693/wardn-hub-backend",
            "ghcr.io/abhi1693/wardn-hub-codex-app-server",
            "ghcr.io/abhi1693/wardn-hub-frontend",
        ]:
            failures.append("Hub reviewed rule must contain exactly its three component packages")
        if re.findall(r"^\s*automerge:\s*([^,\n]+)", hub_rules[0], re.MULTILINE) != ["false"]:
            failures.append("Hub reviewed cohort must disable automerge exactly once")
    if 'matchPackageNames: ["abhi1693/wardn-hub"]' in config:
        failures.append("Hub image automation must follow published containers rather than source releases")
    failures.extend(check_license_image_policy(
        config, REPOSITORY_ROOT / "kubernetes/projects/applications/apps/wardn-license-server"
    ))
    failures.extend(check_license_image_cohort(
        REPOSITORY_ROOT / "kubernetes/projects/applications/apps/wardn-license-server"
    ))
    license_rules = [block for block in re.findall(r"\{[^{}]*\}", config)
                     if 'groupSlug: "wardn-license-server-images"' in block]

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

    # A release event starts these builds; registry tags follow native gates.
    failures.extend(check_registry_tracked_images(config, REPOSITORY_ROOT))

    # The upstream NUT registry also publishes bare-version Helm artifacts.
    # Runtime image updates must retain the -rN family and compare N numerically.
    nut_rules = [
        block
        for block in re.findall(r"\{[^{}]*\}", config)
        if 'matchPackageNames: ["docker.io/instantlinux/nut-upsd"]' in block
    ]
    if len(nut_rules) != 1:
        failures.append("expected one NUT runtime image rule")
    else:
        rule = nut_rules[0]
        versioning = re.search(r'versioning:\s*("[^"\n]+")', rule)
        allowed = re.search(r'allowedVersions:\s*("[^"\n]+")', rule)
        if versioning is None or allowed is None:
            failures.append("NUT image rule needs regex versioning and an allowed-tag filter")
        else:
            versioning_value = json.loads(versioning.group(1))
            allowed_value = json.loads(allowed.group(1))
            if not versioning_value.startswith("regex:") or not (
                allowed_value.startswith("/") and allowed_value.endswith("/")
            ):
                failures.append("NUT image rule must use regex versioning and allowedVersions")
            else:
                version_pattern = re.compile(
                    re.sub(r"\(\?<([A-Za-z]+)>", r"(?P<\1>", versioning_value[6:])
                )
                allowed_pattern = re.compile(allowed_value[1:-1])
                version_parts = ("major", "minor", "patch", "build")
                if not all(part in version_pattern.groupindex for part in version_parts):
                    failures.append("NUT regex must capture major, minor, patch, and numeric build")
                else:
                    parsed_versions = []
                    for tag in ("2.8.3-r4", "2.8.5-r1", "2.8.5-r2", "2.8.5-r10", "2.9.0-r1"):
                        match = version_pattern.fullmatch(tag)
                        if match is None or allowed_pattern.fullmatch(tag) is None:
                            failures.append(f"NUT runtime image tag rejected: {tag}")
                            continue
                        parts = tuple(match.group(part) for part in version_parts)
                        if not all(part is not None and part.isdecimal() for part in parts):
                            failures.append(f"NUT version captures must be numeric: {tag}")
                            continue
                        parsed_versions.append(tuple(int(part) for part in parts))
                    if len(parsed_versions) == 5 and any(
                        left >= right
                        for left, right in zip(parsed_versions, parsed_versions[1:])
                    ):
                        failures.append("NUT regex must order upstream versions and rN builds numerically")

                for tag in (
                    "2.8.5", "0.1.14", "latest", "3.0.0-r1", "2.8.5-r1-alpine",
                    "2.8.5-r1-rc.1", "2.8.5-r", "2.8.5-r1.1",
                ):
                    if allowed_pattern.fullmatch(tag):
                        failures.append(f"NUT non-runtime tag allowed: {tag}")

                deployment_path = (
                    REPOSITORY_ROOT
                    / "kubernetes/projects/home-automation/apps/ups-monitoring/deployment.yaml"
                )
                deployed_tags = re.findall(
                    r"(?m)^\s*image:\s*registry\.home/docker\.io/instantlinux/nut-upsd:([^@\s]+)",
                    deployment_path.read_text(encoding="utf-8"),
                )
                if len(deployed_tags) != 1 or any(
                    version_pattern.fullmatch(tag) is None
                    or allowed_pattern.fullmatch(tag) is None
                    for tag in deployed_tags
                ):
                    failures.append("NUT Deployment must select one guarded -rN runtime image tag")

    failures.extend(check_default_merge_policy(
        config, hub_rules[0] if len(hub_rules) == 1 else None,
        *(license_rules if len(license_rules) == 1 else []),
    ))

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
