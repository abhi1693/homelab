#!/usr/bin/env python3
"""Check Cilium bootstrap/Fleet parity and exercise incident alert scenarios."""

from pathlib import Path
import json
import subprocess
import tempfile

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/projects/system/apps/cilium"
MONITORING = ROOT / "kubernetes/projects/system/apps/cilium-monitoring"
VARIABLES = ROOT / "infrastructure/ansible/inventories/home/group_vars"
TEMPLATES = ROOT / "infrastructure/ansible/roles/cilium/templates"


def main():
    variables = {}
    for name in ("all.yml", "k3s_servers.yml"):
        variables.update(yaml.safe_load((VARIABLES / name).read_text()))
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["to_json"] = json.dumps
    bootstrap = yaml.safe_load(
        environment.get_template("values.yaml.j2").render(**variables)
    )
    desired = yaml.safe_load((APP / "values.yaml").read_text())
    if bootstrap != desired:
        raise SystemExit("Cilium bootstrap values differ from Fleet values")
    helmop = yaml.safe_load((APP / "helmop.yaml").read_text())
    if helmop["spec"]["helm"]["version"] != variables["cilium"]["version"]:
        raise SystemExit("Cilium bootstrap and Fleet chart versions differ")
    for handler in desired["hubble"]["metrics"]["enabled"]:
        _, _, raw_options = handler.partition(":")
        for option in raw_options.split(";"):
            name, _, value = option.partition("=")
            if name in {"sourceContext", "destinationContext"} and value != "namespace":
                raise SystemExit("Hubble context labels must be namespace-only")
            if name in {"query", "labelsContext"}:
                raise SystemExit("Hubble query and arbitrary context labels are disabled")
    print("Cilium bootstrap and Fleet values are identical")

    with tempfile.TemporaryDirectory(prefix="cilium-observability-") as directory:
        temporary = Path(directory)
        rules = yaml.safe_load((MONITORING / "prometheusrule.yaml").read_text())["spec"]
        rules_file = temporary / "rules.yml"
        rules_file.write_text(yaml.safe_dump(rules))
        tests = yaml.safe_load(
            (ROOT / "scripts/tests/fixtures/cilium-prometheus-tests.yaml").read_text()
        )
        tests["rule_files"] = [str(rules_file)]
        tests_file = temporary / "tests.yml"
        tests_file.write_text(yaml.safe_dump(tests))
        subprocess.run(["promtool", "check", "rules", str(rules_file)], check=True)
        subprocess.run(["promtool", "test", "rules", str(tests_file)], check=True)
        print(f'Validated {len(tests["tests"])} Cilium incident alert scenarios')


if __name__ == "__main__":
    main()
