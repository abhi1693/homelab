#!/usr/bin/env python3
"""Read-only qualification of a published Harbor chart and ARM64 image cohort."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {"harbor-core", "harbor-portal", "harbor-jobservice", "harbor-registryctl",
              "registry-photon", "trivy-adapter-photon", "harbor-exporter"}


def evaluate(candidate, catalog, inspections):
    version = candidate["target_version"].removeprefix("v")
    images = candidate["images"]
    blockers = []
    if {entry["component"] for entry in images} != COMPONENTS or len(images) != len(COMPONENTS):
        blockers.append("The complete seven-component runtime image cohort is required")
    matching = [chart for chart in catalog.get("entries", {}).get("harbor", [])
                if str(chart.get("appVersion", "")).removeprefix("v") == version
                and not re.search(r"[a-zA-Z]", str(chart.get("version", "")))]
    if not matching:
        blockers.append(f"No published Harbor Helm chart targets application {version}")
    for entry in images:
        name = entry["component"]
        image = inspections.get(name, {})
        if entry["destination"] != "ghcr.io/abhi1693/" + name + ":v" + version:
            blockers.append(f"{name}: image tag is outside the requested release cohort")
        if entry["source"] != "docker.io/goharbor/" + name + ":v" + version:
            blockers.append(f"{name}: source is outside the official upstream release cohort")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", entry["digest"]):
            blockers.append(f"{name}: invalid immutable digest")
        if image.get("Architecture") != "arm64" or image.get("Digest") != entry["digest"]:
            blockers.append(f"{name}: published ARM64 digest does not match the candidate")
    return {"ready": not blockers, "target_version": version,
            "matching_chart_versions": [chart["version"] for chart in matching],
            "blockers": blockers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path,
                        default=ROOT / "kubernetes/images/harbor/upgrade-candidate.json")
    parser.add_argument("--chart-index-file", type=Path)
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text())
    if args.chart_index_file:
        catalog = yaml.safe_load(args.chart_index_file.read_text())
    else:
        with urllib.request.urlopen("https://helm.goharbor.io/index.yaml", timeout=30) as response:
            catalog = yaml.safe_load(response.read())
    inspections = {}
    for entry in candidate["images"]:
        result = subprocess.run(["skopeo", "inspect", "--no-creds", "--no-tags",
                                 "--override-arch", "arm64", "docker://" + entry["destination"]],
                                capture_output=True, text=True, timeout=45)
        if result.returncode == 0:
            inspections[entry["component"]] = json.loads(result.stdout)
    report = evaluate(candidate, catalog, inspections)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
