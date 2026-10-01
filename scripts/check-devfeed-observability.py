#!/usr/bin/env python3
"""Check DevFeed PromQL, alert scenarios and dashboard queries without a cluster."""
import json
from pathlib import Path
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'kubernetes/projects/applications/apps/devfeed'
with tempfile.TemporaryDirectory(prefix='devfeed-observability-') as directory:
    temp = Path(directory)
    rule = yaml.safe_load((APP / 'prometheusrule.yaml').read_text())['spec']
    for group in rule['groups']:
        for item in group['rules']:
            if 'record' in item:
                assert item['record'] not in item['expr'], 'Recording rules must not read themselves'
    (temp / 'rules.yml').write_text(yaml.safe_dump(rule))
    tests = yaml.safe_load((ROOT / 'scripts/tests/fixtures/devfeed-prometheus-tests.yaml').read_text())
    tests['rule_files'] = [str(temp / 'rules.yml')]
    (temp / 'tests.yml').write_text(yaml.safe_dump(tests))
    subprocess.run(['promtool', 'check', 'rules', str(temp / 'rules.yml')], check=True)
    subprocess.run(['promtool', 'test', 'rules', str(temp / 'tests.yml')], check=True)
    expressions = []
    for filename in APP.glob('devfeed-*.yaml'):
        document = yaml.safe_load(filename.read_text())
        for value in document.get('data', {}).values():
            dashboard = json.loads(value)
            assert dashboard['uid'] and dashboard['panels']
            for panel in dashboard['panels']:
                if panel.get('datasource', {}).get('type') != 'prometheus':
                    continue
                for target in panel.get('targets', []):
                    expr = target.get('expr', '').replace('$service', '.*').replace('$queue', '.*')
                    expressions.append({'record': f'devfeed:dashboard_check_{len(expressions)}', 'expr': expr})
    (temp / 'dashboards.yml').write_text(yaml.safe_dump({'groups': [{'name': 'dashboard-validation', 'rules': expressions}]}))
    subprocess.run(['promtool', 'check', 'rules', str(temp / 'dashboards.yml')], check=True)
    print(f'Validated {len(expressions)} dashboard PromQL queries and {len(tests["tests"])} alert scenarios')
