#!/usr/bin/env python3
"""Validate Git-owned Kubernetes workload catalog entries."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPOSITORY_ROOT / "infrastructure/netbox/workload-catalog.schema.json"
DEFAULT_NETBOX_SCHEMA = (
    REPOSITORY_ROOT / "infrastructure/netbox/workload-catalog-netbox-schema.yaml"
)
DEFAULT_EXCLUSIONS = (
    REPOSITORY_ROOT / "infrastructure/netbox/workload-catalog-exclusions.yaml"
)
CATALOG_GLOBS = (
    "kubernetes/projects/*/apps/*/catalog.yaml",
    "infrastructure/netbox/platform-catalogs/*.yaml",
)
PROJECT_CATALOG_GLOB = CATALOG_GLOBS[0]
APP_DIR_GLOB = "kubernetes/projects/*/apps/*"
EXPECTED_CUSTOM_OBJECT_TYPES = {
    "application",
    "dependency",
    "endpoint",
    "kubernetes_workload",
    "persistent_store",
}
RESERVED_CUSTOM_OBJECT_FIELDS = {
    "created",
    "custom_object_type",
    "id",
    "images",
    "jobs",
    "last_updated",
    "model",
    "objects",
    "owner",
    "tags",
    "url",
}


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def expected_key(cluster: str, item_type: str, item: dict[str, object]) -> str:
    if item_type == "workloads":
        return "/".join(
            (
                cluster,
                str(item["namespace"]),
                str(item["apiGroup"]),
                str(item["kind"]).lower(),
                str(item["name"]),
            )
        )
    if item_type == "persistentStores":
        return "/".join(
            (
                cluster,
                str(item["namespace"]),
                str(item["type"]).lower(),
                str(item["name"]),
            )
        )
    raise ValueError(f"unsupported key type: {item_type}")


def validate_netbox_schema(schema_path: Path) -> list[str]:
    errors: list[str] = []
    document = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    if document.get("kind") != "NetBoxCustomObjectSchema":
        errors.append(f"{relative(schema_path)}: kind must be NetBoxCustomObjectSchema")
        return errors
    object_types = document.get("spec", {}).get("objectTypes", [])
    actual_types = {item.get("name") for item in object_types}
    if actual_types != EXPECTED_CUSTOM_OBJECT_TYPES:
        errors.append(
            f"{relative(schema_path)}: expected object types "
            f"{sorted(EXPECTED_CUSTOM_OBJECT_TYPES)}, got {sorted(actual_types)}"
        )
    seen_slugs: set[str] = set()
    for object_type in object_types:
        name = object_type.get("name", "")
        slug = object_type.get("slug", "")
        location = f"{relative(schema_path)}:{name or '<unnamed>'}"
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9_]*[a-z0-9])?", name) or "__" in name:
            errors.append(f"{location}: invalid NetBox internal object type name")
        if slug in seen_slugs:
            errors.append(f"{location}: duplicate slug {slug!r}")
        seen_slugs.add(slug)
        fields = object_type.get("fields", [])
        field_names = [field.get("name") for field in fields]
        duplicates = sorted({field for field in field_names if field_names.count(field) > 1})
        if duplicates:
            errors.append(f"{location}: duplicate fields {duplicates}")
        collisions = sorted(set(field_names) & RESERVED_CUSTOM_OBJECT_FIELDS)
        if collisions:
            errors.append(f"{location}: fields collide with NetBox model fields: {collisions}")
        primary_fields = [field.get("name") for field in fields if field.get("primary")]
        if len(primary_fields) != 1:
            errors.append(f"{location}: expected one primary field, got {primary_fields}")
    return errors


def validate_catalogs(
    schema_path: Path, netbox_schema_path: Path, exclusions_path: Path
) -> list[str]:
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = validate_netbox_schema(netbox_schema_path)
    seen: dict[str, dict[str, str]] = {
        "applications": {},
        "workloads": {},
        "persistentStores": {},
        "endpoints": {},
        "dependencies": {},
    }
    catalogs = sorted(
        {path for pattern in CATALOG_GLOBS for path in REPOSITORY_ROOT.glob(pattern)}
    )
    if not catalogs:
        return [f"no catalogs matched {CATALOG_GLOBS}"]

    project_catalogs = set(REPOSITORY_ROOT.glob(PROJECT_CATALOG_GLOB))
    catalog_directories = {relative(path.parent) for path in project_catalogs}
    exclusions_document = yaml.safe_load(exclusions_path.read_text(encoding="utf-8"))
    exclusions = exclusions_document.get("spec", {}).get("exclusions", [])
    excluded_paths: set[str] = set()
    for index, exclusion in enumerate(exclusions):
        path = exclusion.get("path", "")
        location = f"{relative(exclusions_path)}:spec.exclusions[{index}]"
        if path in excluded_paths:
            errors.append(f"{location}: duplicate path {path!r}")
        excluded_paths.add(path)
        if exclusion.get("disposition") not in {"component", "retired", "support"}:
            errors.append(f"{location}: invalid disposition")
        if not exclusion.get("application") or not exclusion.get("reason"):
            errors.append(f"{location}: application and reason are required")
        if not (REPOSITORY_ROOT / path).is_dir():
            errors.append(f"{location}: directory does not exist: {path}")
    overlap = sorted(catalog_directories & excluded_paths)
    if overlap:
        errors.append(f"cataloged application directories also excluded: {overlap}")
    app_directories = {
        relative(path)
        for path in REPOSITORY_ROOT.glob(APP_DIR_GLOB)
        if path.is_dir()
    }
    uncovered = sorted(app_directories - catalog_directories - excluded_paths)
    stale_exclusions = sorted(excluded_paths - app_directories)
    if uncovered:
        errors.append(f"unclassified project app directories: {uncovered}")
    if stale_exclusions:
        errors.append(f"exclusions do not match project app directories: {stale_exclusions}")

    for catalog_path in catalogs:
        catalog_rel = relative(catalog_path)
        try:
            catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{catalog_rel}: invalid YAML: {exc}")
            continue

        validation_errors = sorted(validator.iter_errors(catalog), key=lambda err: list(err.path))
        for error in validation_errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"{catalog_rel}:{location}: {error.message}")
        if validation_errors:
            continue

        metadata = catalog["metadata"]
        spec = catalog["spec"]
        app_name = metadata["name"]
        app_dir = catalog_path.parent
        if catalog_path in project_catalogs:
            expected_git_path = relative(app_dir)
            if spec["gitPath"] != expected_git_path:
                errors.append(
                    f"{catalog_rel}:spec.gitPath: expected {expected_git_path!r}, got {spec['gitPath']!r}"
                )
            fleetignore_path = app_dir / ".fleetignore"
            if not fleetignore_path.exists():
                errors.append(f"{catalog_rel}: app directory must contain .fleetignore")
            else:
                fleetignore_entries = {
                    line.strip()
                    for line in fleetignore_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                }
                if "catalog.yaml" not in fleetignore_entries:
                    errors.append(f"{catalog_rel}: .fleetignore must exclude catalog.yaml")

        previous = seen["applications"].setdefault(app_name, catalog_rel)
        if previous != catalog_rel:
            errors.append(f"{catalog_rel}: duplicate application name {app_name!r}; first in {previous}")

        for item_type in ("workloads", "persistentStores"):
            for index, item in enumerate(spec.get(item_type, [])):
                actual_key = item["key"]
                generated_key = expected_key(spec["cluster"], item_type, item)
                if actual_key != generated_key:
                    errors.append(
                        f"{catalog_rel}:spec.{item_type}[{index}].key: "
                        f"expected {generated_key!r}, got {actual_key!r}"
                    )

        for item_type in ("workloads", "persistentStores", "endpoints", "dependencies"):
            for index, item in enumerate(spec.get(item_type, [])):
                key = item["key"]
                item_location = f"{catalog_rel}:spec.{item_type}[{index}]"
                previous = seen[item_type].setdefault(key, item_location)
                if previous != item_location:
                    errors.append(f"{item_location}: duplicate key {key!r}; first at {previous}")
                source_path = item.get("sourcePath")
                if source_path and not (REPOSITORY_ROOT / source_path).exists():
                    errors.append(f"{item_location}.sourcePath: path does not exist: {source_path}")

        for field in ("gitPath", "runbook"):
            source_path = spec.get(field)
            if source_path and not (REPOSITORY_ROOT / source_path).exists():
                errors.append(f"{catalog_rel}:spec.{field}: path does not exist: {source_path}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--netbox-schema", type=Path, default=DEFAULT_NETBOX_SCHEMA)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS)
    args = parser.parse_args()
    errors = validate_catalogs(
        args.schema.resolve(), args.netbox_schema.resolve(), args.exclusions.resolve()
    )
    if errors:
        print("Workload catalog validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    catalogs = sorted(
        {path for pattern in CATALOG_GLOBS for path in REPOSITORY_ROOT.glob(pattern)}
    )
    workload_count = sum(
        len(yaml.safe_load(path.read_text(encoding="utf-8"))["spec"]["workloads"])
        for path in catalogs
    )
    exclusions = yaml.safe_load(
        args.exclusions.resolve().read_text(encoding="utf-8")
    )["spec"]["exclusions"]
    print(
        f"Validated {len(catalogs)} application catalogs, "
        f"{workload_count} workloads, and {len(exclusions)} classified exclusions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
