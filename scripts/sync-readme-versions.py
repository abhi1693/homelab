#!/usr/bin/env python3
"""Sync root README version badges from Git-managed source files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import yaml
except ImportError as exc:  # pragma: no cover - operator-facing dependency check
    raise SystemExit("error: PyYAML is required for this script") from exc


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

K3S_VARS = ROOT / "infrastructure/ansible/inventories/home/group_vars/all.yml"
K3S_SERVER_VARS = ROOT / "infrastructure/ansible/inventories/home/group_vars/k3s_servers.yml"
K3S_NODE_VARS = ROOT / "infrastructure/ansible/inventories/home/group_vars/k3s_nodes.yml"
RENOVATE_CRONJOB = ROOT / "kubernetes/projects/applications/apps/renovate/cronjob.yaml"


@dataclass(frozen=True)
class VersionValue:
    key: str
    label: str
    value: str
    source: Path
    color: str
    logo: str | None = None
    logo_color: str | None = "white"

    @property
    def alt(self) -> str:
        return f"{self.label} {self.value}"

    @property
    def src(self) -> str:
        params = [("style", "flat-square")]
        if self.logo:
            params.append(("logo", self.logo))
        if self.logo_color:
            params.append(("logoColor", self.logo_color))
        query = "&amp;".join(f"{quote(k)}={quote(v)}" for k, v in params)
        label = quote(self.label, safe="")
        value = quote(self.value, safe="")
        return f"https://img.shields.io/badge/{label}-{value}-{self.color}?{query}"


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return ROOT / path


def load_yaml(path: Path) -> Any:
    if not path.exists():
        die(f"source file not found: {display_path(path)}")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def require_path(data: dict[str, Any], path: tuple[str, ...], source: Path) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            joined = ".".join(path)
            die(f"{display_path(source)} is missing {joined}")
        current = current[key]
    if current in (None, ""):
        joined = ".".join(path)
        die(f"{display_path(source)} has empty {joined}")
    return current


def image_tag(image: str) -> str:
    without_digest = image.split("@", 1)[0]
    last_segment = without_digest.rsplit("/", 1)[-1]
    if ":" not in last_segment:
        die(f"image does not include a tag: {image}")
    return last_segment.rsplit(":", 1)[1]


def renovate_version() -> str:
    cronjob = load_yaml(RENOVATE_CRONJOB)
    try:
        containers = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    except KeyError as exc:
        die(f"{display_path(RENOVATE_CRONJOB)} does not look like a CronJob: missing {exc}")

    for container in containers:
        if container.get("name") == "renovate":
            return image_tag(container.get("image", ""))
    die(f"{display_path(RENOVATE_CRONJOB)} has no container named renovate")


def longhorn_app_version(chart_version: str) -> str:
    if "+up" in chart_version:
        return chart_version.split("+up", 1)[1]
    return chart_version


def collect_values() -> list[VersionValue]:
    k3s_vars = load_yaml(K3S_VARS)
    server_vars = load_yaml(K3S_SERVER_VARS)
    node_vars = load_yaml(K3S_NODE_VARS)

    k3s = str(require_path(k3s_vars, ("k3s", "version"), K3S_VARS))
    cilium = str(require_path(server_vars, ("cilium", "version"), K3S_SERVER_VARS))
    rancher = str(require_path(server_vars, ("rancher", "chart_version"), K3S_SERVER_VARS))
    longhorn_chart = str(require_path(node_vars, ("longhorn", "chart_version"), K3S_NODE_VARS))

    return [
        VersionValue(
            key="renovate",
            label="Renovate",
            value=renovate_version(),
            source=RENOVATE_CRONJOB,
            color="1A1F6C",
            logo="renovatebot",
        ),
        VersionValue(
            key="k3s",
            label="K3s",
            value=k3s,
            source=K3S_VARS,
            color="326CE5",
            logo="k3s",
        ),
        VersionValue(
            key="cilium",
            label="Cilium",
            value=cilium,
            source=K3S_SERVER_VARS,
            color="F8C517",
            logo="cilium",
            logo_color="black",
        ),
        VersionValue(
            key="rancher",
            label="Rancher",
            value=rancher,
            source=K3S_SERVER_VARS,
            color="0075A8",
            logo="rancher",
        ),
        VersionValue(
            key="longhorn",
            label="Longhorn",
            value=longhorn_app_version(longhorn_chart),
            source=K3S_NODE_VARS,
            color="6D4AFF",
            logo=None,
            logo_color=None,
        ),
    ]


def replace_badge(text: str, value: VersionValue) -> tuple[str, bool]:
    encoded_label = quote(value.label, safe="")
    pattern = re.compile(
        rf'(<img alt="){re.escape(value.label)} [^"]+(" src=")'
        rf'https://img\.shields\.io/badge/{re.escape(encoded_label)}-[^"]+(">)'
    )

    updated, count = pattern.subn(
        lambda match: f"{match.group(1)}{value.alt}{match.group(2)}{value.src}{match.group(3)}",
        text,
        count=1,
    )
    if count != 1:
        die(f"README badge not found for {value.label}")
    return updated, updated != text


def replace_table_version(text: str, label: str, version: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(\| [^|]*{re.escape(label)} `)[^`]+(`[^|]*\|)")
    updated, count = pattern.subn(
        lambda match: f"{match.group(1)}{version}{match.group(2)}",
        text,
        count=1,
    )
    if count != 1:
        die(f"README At A Glance row not found for {label}")
    return updated, updated != text


def expected_readme(text: str, values: list[VersionValue]) -> tuple[str, list[str]]:
    changed: list[str] = []
    by_key = {value.key: value for value in values}

    for value in values:
        text, did_change = replace_badge(text, value)
        if did_change:
            changed.append(f"{value.label} badge")

    for key, label in (("k3s", "K3s"), ("cilium", "Cilium")):
        text, did_change = replace_table_version(text, label, by_key[key].value)
        if did_change:
            changed.append(f"{label} At A Glance row")

    return text, changed


def print_values(values: list[VersionValue], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    value.key: {
                        "label": value.label,
                        "value": value.value,
                        "source": str(value.source.relative_to(ROOT)),
                    }
                    for value in values
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    width = max(len(value.label) for value in values)
    for value in values:
        source = display_path(value.source)
        print(f"{value.label:<{width}}  {value.value:<16}  {source}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read pinned versions from source files and sync static root README badges.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if README.md is out of sync")
    mode.add_argument("--update", action="store_true", help="rewrite README.md with current values")
    p.add_argument("--json", action="store_true", help="print values as JSON when not using --check/--update")
    p.add_argument("--readme", default=README, type=Path, help="README path to check or update")
    return p


def main() -> None:
    args = parser().parse_args()
    readme = repo_path(args.readme)
    values = collect_values()

    if not args.check and not args.update:
        print_values(values, as_json=args.json)
        return

    original = readme.read_text(encoding="utf-8")
    expected, changed = expected_readme(original, values)

    if args.check:
        if changed:
            print(f"{display_path(readme)} is out of sync:")
            for item in changed:
                print(f"  - {item}")
            print("Run: scripts/sync-readme-versions.py --update")
            raise SystemExit(1)
        print(f"{display_path(readme)} version badges are in sync")
        return

    if changed:
        readme.write_text(expected, encoding="utf-8")
        print(f"updated {display_path(readme)}:")
        for item in changed:
            print(f"  - {item}")
    else:
        print(f"{display_path(readme)} already in sync")


if __name__ == "__main__":
    main()
