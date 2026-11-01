#!/usr/bin/env python3
"""Exercise actual OS logging rules against coverage, queue and final-loss fixtures."""

from pathlib import Path
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/projects/system/apps/alloy-node-logs"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="os-logging-observability-") as directory:
        temporary = Path(directory)
        rules = yaml.safe_load((APP / "prometheusrule.yaml").read_text())["spec"]
        rules_file = temporary / "rules.yml"
        rules_file.write_text(yaml.safe_dump(rules))
        tests = yaml.safe_load((ROOT / "scripts/tests/fixtures/os-logging-prometheus-tests.yaml").read_text())
        tests["rule_files"] = [str(rules_file)]
        tests_file = temporary / "tests.yml"
        tests_file.write_text(yaml.safe_dump(tests))
        subprocess.run(["promtool", "check", "rules", str(rules_file)], check=True)
        subprocess.run(["promtool", "test", "rules", str(tests_file)], check=True)
        print(f'Validated {len(tests["tests"])} OS logging alert scenarios')


if __name__ == "__main__":
    main()
