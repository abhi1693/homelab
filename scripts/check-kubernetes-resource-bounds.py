#!/usr/bin/env python3
"""Validate authored workload resources and recommendation profile bounds."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml


SKIPPED_FILENAMES = {
    "crd-values.yaml",
    "fleet.yaml",
    "kustomizeconfig.yaml",
    "values.yaml",
}
WORKLOAD_TEMPLATE_PATHS = {
    "CronJob": ("spec", "jobTemplate", "spec", "template", "spec"),
    "DaemonSet": ("spec", "template", "spec"),
    "Deployment": ("spec", "template", "spec"),
    "Job": ("spec", "template", "spec"),
    "Pod": ("spec",),
    "ReplicaSet": ("spec", "template", "spec"),
    "StatefulSet": ("spec", "template", "spec"),
}
REQUIRED_RESOURCES = (
    ("requests", "cpu"),
    ("requests", "memory"),
    ("limits", "memory"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check direct Kubernetes Pod templates for CPU and memory requests "
            "plus a memory limit."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path("kubernetes")],
        help="Files or directories to inspect (default: kubernetes).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Inspect a rendered multi-document YAML stream from standard input.",
    )
    parser.add_argument(
        "--source-label",
        default="<stdin>",
        help="Source label used in --stdin diagnostics (default: <stdin>).",
    )
    return parser.parse_args()


def yaml_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(
                candidate
                for pattern in ("*.yaml", "*.yml")
                for candidate in path.rglob(pattern)
            )
        else:
            raise FileNotFoundError(path)

        for candidate in candidates:
            if candidate.name in SKIPPED_FILENAMES:
                continue
            if "chart/templates" in candidate.as_posix():
                continue
            if candidate.name == "Chart.yaml" and "chart" in candidate.parts:
                continue
            yield candidate


def nested_map(document: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    value: Any = document
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def missing_resources(container: dict[str, Any]) -> list[str]:
    resources = container.get("resources")
    if not isinstance(resources, dict):
        resources = {}

    missing: list[str] = []
    for section, resource in REQUIRED_RESOURCES:
        values = resources.get(section)
        if not isinstance(values, dict) or values.get(resource) in (None, ""):
            missing.append(f"{section}.{resource}")
    return missing


def check_document(
    document: dict[str, Any], source: Path, document_index: int
) -> list[str]:
    kind = document.get("kind")
    path = WORKLOAD_TEMPLATE_PATHS.get(kind)
    if path is None:
        return []

    pod_spec = nested_map(document, path)
    if pod_spec is None:
        return [f"{source}: document {document_index}: {kind} has no Pod spec"]

    metadata = document.get("metadata")
    name = metadata.get("name", "<unnamed>") if isinstance(metadata, dict) else "<unnamed>"
    namespace = (
        metadata.get("namespace", "<default>")
        if isinstance(metadata, dict)
        else "<default>"
    )
    failures: list[str] = []

    for container_type in ("initContainers", "containers"):
        containers = pod_spec.get(container_type, [])
        if not isinstance(containers, list):
            failures.append(
                f"{source}: {kind}/{namespace}/{name}: {container_type} is not a list"
            )
            continue
        for container in containers:
            if not isinstance(container, dict):
                failures.append(
                    f"{source}: {kind}/{namespace}/{name}: malformed {container_type} entry"
                )
                continue
            missing = missing_resources(container)
            if missing:
                container_name = container.get("name", "<unnamed>")
                failures.append(
                    f"{source}: {kind}/{namespace}/{name}: "
                    f"{container_type}/{container_name} missing {', '.join(missing)}"
                )
    return failures


def check_application_profile(
    document: dict[str, Any], source: Path, document_index: int
) -> list[str]:
    if document.get("kind") != "ApplicationProfile":
        return []

    metadata = document.get("metadata")
    name = (
        metadata.get("name", "<unnamed>")
        if isinstance(metadata, dict)
        else "<unnamed>"
    )
    spec = document.get("spec")
    workloads = spec.get("workloads", []) if isinstance(spec, dict) else []
    if not isinstance(workloads, list):
        return [
            f"{source}: document {document_index}: ApplicationProfile/{name}: "
            "workloads is not a list"
        ]

    failures: list[str] = []
    for workload in workloads:
        if not isinstance(workload, dict):
            continue
        workload_name = workload.get("name", "<unnamed>")
        bounds = workload.get("bounds")
        if not isinstance(bounds, dict):
            continue
        for resource in ("cpu", "memory"):
            resource_bounds = bounds.get(resource)
            if not isinstance(resource_bounds, dict):
                continue
            minimum_change = resource_bounds.get("minChangePercent")
            maximum_decrease = resource_bounds.get("maxDecreasePercent")
            if not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in (minimum_change, maximum_decrease)
            ):
                continue
            if minimum_change >= maximum_decrease:
                failures.append(
                    f"{source}: ApplicationProfile/{name}: workload/{workload_name}: "
                    f"bounds.{resource}.minChangePercent ({minimum_change}) must be "
                    f"less than maxDecreasePercent ({maximum_decrease})"
                )
    return failures


def main() -> int:
    args = parse_args()
    failures: list[str] = []
    checked_documents = 0
    checked_profiles = 0

    if args.stdin:
        try:
            documents_by_source = [
                (Path(args.source_label), list(yaml.safe_load_all(sys.stdin)))
            ]
        except yaml.YAMLError as error:
            print(f"{args.source_label}: could not parse YAML: {error}", file=sys.stderr)
            return 1
    else:
        try:
            candidates = list(dict.fromkeys(yaml_files(args.paths)))
        except FileNotFoundError as error:
            print(f"error: path not found: {error}", file=sys.stderr)
            return 2

        documents_by_source: list[tuple[Path, list[Any]]] = []
        for source in candidates:
            try:
                with source.open(encoding="utf-8") as manifest:
                    documents_by_source.append((source, list(yaml.safe_load_all(manifest))))
            except (OSError, yaml.YAMLError) as error:
                failures.append(f"{source}: could not parse YAML: {error}")

    for source, documents in documents_by_source:
        for document_index, document in enumerate(documents, start=1):
            if not isinstance(document, dict):
                continue
            if document.get("kind") in WORKLOAD_TEMPLATE_PATHS:
                checked_documents += 1
            if document.get("kind") == "ApplicationProfile":
                checked_profiles += 1
            failures.extend(check_document(document, source, document_index))
            failures.extend(check_application_profile(document, source, document_index))

    if failures:
        print("Kubernetes resource-bound policy violations:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        f"Checked {checked_documents} direct workload documents: "
        "CPU/memory requests and memory limits are present; "
        f"checked {checked_profiles} recommendation profiles for compatible "
        "change thresholds."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
