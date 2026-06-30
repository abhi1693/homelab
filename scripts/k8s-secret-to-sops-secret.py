#!/usr/bin/env python3
"""Mirror live Kubernetes Secret data into an encrypted SopsSecret manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - operator-facing dependency check
    raise SystemExit("error: PyYAML is required for this script") from exc


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def need(command: str) -> None:
    if shutil.which(command) is None:
        die(f"required command not found: {command}")


def run(command: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        die(f"command failed: {' '.join(command)}\n{detail}")
    return completed.stdout


def parse_key_value(value: str, flag: str) -> tuple[str, str]:
    if "=" not in value:
        die(f"{flag} expects KEY=VALUE, got {value!r}")
    key, parsed_value = value.split("=", 1)
    if not key:
        die(f"{flag} key cannot be empty")
    return key, parsed_value


def parse_secret_spec(value: str) -> tuple[str, str]:
    if "=" not in value:
        return value, value
    source, target = value.split("=", 1)
    if not source or not target:
        die(f"secret mapping expects SOURCE=TARGET, got {value!r}")
    return source, target


def secret_from_cluster(namespace: str, name: str) -> dict[str, Any]:
    raw = run(["kubectl", "-n", namespace, "get", "secret", name, "-o", "json"])
    return json.loads(raw)


def selected_metadata(
    source: dict[str, Any],
    *,
    preserve_labels: bool,
    preserve_annotations: bool,
    labels: list[str],
    annotations: list[str],
) -> dict[str, Any]:
    metadata = source.get("metadata") or {}
    template: dict[str, Any] = {}

    merged_labels: dict[str, str] = {}
    if preserve_labels:
        merged_labels.update(metadata.get("labels") or {})
    for item in labels:
        key, value = parse_key_value(item, "--label")
        merged_labels[key] = value
    if merged_labels:
        template["labels"] = merged_labels

    merged_annotations: dict[str, str] = {}
    if preserve_annotations:
        merged_annotations.update(metadata.get("annotations") or {})
        merged_annotations.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    for item in annotations:
        key, value = parse_key_value(item, "--annotation")
        merged_annotations[key] = value
    if merged_annotations:
        template["annotations"] = merged_annotations

    return template


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    secret_specs = [parse_secret_spec(value) for value in args.secret]
    target_namespace = args.target_namespace or args.namespace
    sops_name = args.sops_name
    if sops_name is None:
        if len(secret_specs) == 1:
            sops_name = f"{secret_specs[0][1]}-secrets"
        else:
            sops_name = f"{target_namespace}-secrets"

    templates: list[dict[str, Any]] = []
    for source_name, target_name in secret_specs:
        source = secret_from_cluster(args.namespace, source_name)
        data = source.get("data") or {}
        if not data:
            die(f"{args.namespace}/{source_name} has no data")

        template = {
            "name": target_name,
            "type": source.get("type") or "Opaque",
            "data": dict(sorted(data.items())),
        }
        template.update(
            selected_metadata(
                source,
                preserve_labels=args.preserve_labels,
                preserve_annotations=args.preserve_annotations,
                labels=args.label,
                annotations=args.annotation,
            )
        )
        templates.append(template)

    return {
        "apiVersion": "isindir.github.com/v1alpha3",
        "kind": "SopsSecret",
        "metadata": {
            "name": sops_name,
            "namespace": target_namespace,
        },
        "spec": {
            "suspend": False,
            "enforceOwnership": args.enforce_ownership,
            "secretTemplates": templates,
        },
    }


def encrypted_yaml(plaintext_yaml: str, output: Path, sops_config: Path) -> str:
    command = [
        "sops",
        "--config",
        str(sops_config),
        "--filename-override",
        str(output),
        "--encrypt",
        "/dev/stdin",
    ]
    return run(command, input_text=plaintext_yaml)


def write_output(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        die(f"output exists: {path} (pass --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def parser() -> argparse.ArgumentParser:
    example = """examples:
  # Mirror one Secret, preserving the live name.
  scripts/k8s-secret-to-sops-secret.py -n indexly indexly \\
    -o kubernetes/projects/applications/apps/indexly/secrets.sops.yaml

  # Mirror and rename the target Secret.
  scripts/k8s-secret-to-sops-secret.py -n indexly indexly-runtime=indexly \\
    --sops-name indexly-secrets \\
    -o kubernetes/projects/applications/apps/indexly/secrets.sops.yaml

  # Mirror Rancher project-scoped image pull secrets from the backing namespace.
  scripts/k8s-secret-to-sops-secret.py -n local-p-applications \\
    --preserve-labels \\
    --sops-name applications-project-secrets \\
    harbor-registry ghcr-home-lab \\
    -o kubernetes/projects/applications/_project/secrets.sops.yaml
"""
    p = argparse.ArgumentParser(
        description="Download live Kubernetes Secret data and write an encrypted SopsSecret manifest.",
        epilog=example,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("secret", nargs="+", help="Secret name, or SOURCE=TARGET to rename the generated Secret")
    p.add_argument("-n", "--namespace", required=True, help="source Kubernetes namespace")
    p.add_argument("--target-namespace", help="SopsSecret namespace; defaults to --namespace")
    p.add_argument("--sops-name", help="metadata.name for the generated SopsSecret")
    p.add_argument("-o", "--output", required=True, type=Path, help="encrypted output file, normally secrets.sops.yaml")
    p.add_argument("--sops-config", default=Path(".sops.yaml"), type=Path, help="SOPS config path")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p.add_argument("--no-enforce-ownership", dest="enforce_ownership", action="store_false", help="set spec.enforceOwnership=false")
    p.set_defaults(enforce_ownership=True)
    p.add_argument("--preserve-labels", action="store_true", help="copy labels from each source Secret into its template")
    p.add_argument("--preserve-annotations", action="store_true", help="copy annotations from each source Secret into its template")
    p.add_argument("--label", action="append", default=[], help="add template label KEY=VALUE; repeatable")
    p.add_argument("--annotation", action="append", default=[], help="add template annotation KEY=VALUE; repeatable")
    return p


def main() -> None:
    args = parser().parse_args()
    need("kubectl")
    need("sops")

    output = args.output
    if not output.name.endswith((".sops.yaml", ".sops.yml")):
        die("output file must end in .sops.yaml or .sops.yml so .sops.yaml rules apply")
    if not args.sops_config.exists():
        die(f"SOPS config not found: {args.sops_config}")

    manifest = build_manifest(args)
    plaintext = yaml.safe_dump(manifest, sort_keys=False, explicit_start=True)
    encrypted = encrypted_yaml(plaintext, output, args.sops_config)
    write_output(output, encrypted, force=args.force)

    targets = ", ".join(template["name"] for template in manifest["spec"]["secretTemplates"])
    print(f"wrote {output}")
    print(f"SopsSecret {manifest['metadata']['namespace']}/{manifest['metadata']['name']} manages: {targets}")


if __name__ == "__main__":
    main()
