#!/usr/bin/env python3
"""Validate PostgreSQL alert syntax and primary/table-threshold scenarios."""
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'kubernetes/projects/database/apps/postgresql'
with tempfile.TemporaryDirectory(prefix='postgresql-observability-') as directory:
    temp = Path(directory)
    rules = yaml.safe_load((APP / 'prometheusrule.yaml').read_text())['spec']
    (temp / 'rules.yml').write_text(yaml.safe_dump(rules))
    tests = yaml.safe_load(
        (ROOT / 'scripts/tests/fixtures/postgresql-prometheus-tests.yaml').read_text()
    )
    tests['rule_files'] = [str(temp / 'rules.yml')]
    (temp / 'tests.yml').write_text(yaml.safe_dump(tests))
    subprocess.run(['promtool', 'check', 'rules', str(temp / 'rules.yml')], check=True)
    subprocess.run(['promtool', 'test', 'rules', str(temp / 'tests.yml')], check=True)
    print(f'Validated {len(tests["tests"])} PostgreSQL alert scenarios')
