#!/usr/bin/env python3
"""Validate PostgreSQL alert syntax, coverage and metric-unit scenarios."""
import argparse
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'kubernetes/projects/database/apps/postgresql'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rendered-cluster', type=Path,
                    help='Include PrometheusRule groups from the exact Helm chart render')
args = parser.parse_args()
values = yaml.safe_load((APP / 'values.yaml').read_text())
expected_exclusions = {'CNPGClusterPhysicalReplicationLagWarning',
                       'CNPGClusterPhysicalReplicationLagCritical'}
actual_exclusions = set(values['cluster']['monitoring']['prometheusRule']['excludeRules'])
if actual_exclusions != expected_exclusions:
    raise SystemExit('Replication alert exclusions must retain the general warning and only replace the two physical defaults')
with tempfile.TemporaryDirectory(prefix='postgresql-observability-') as directory:
    temp = Path(directory)
    rules = yaml.safe_load((APP / 'prometheusrule.yaml').read_text())['spec']
    (temp / 'rules.yml').write_text(yaml.safe_dump(rules))
    tests = yaml.safe_load(
        (ROOT / 'scripts/tests/fixtures/postgresql-prometheus-tests.yaml').read_text()
    )
    if args.rendered_cluster:
        for resource in yaml.safe_load_all(args.rendered_cluster.read_text()):
            if resource and resource.get('kind') == 'PrometheusRule':
                rules['groups'].extend(resource['spec']['groups'])
        alerts = [rule['alert'] for group in rules['groups'] for rule in group['rules'] if 'alert' in rule]
        if len(alerts) != len(set(alerts)):
            raise SystemExit('A default and owned alert share the same name')
        if alerts.count('CNPGClusterHighReplicationLag') != 1 or alerts.count('CNPGClusterPhysicalReplicationLagCritical') != 1:
            raise SystemExit('Require one general warning and one physical critical alert')
        if 'CNPGClusterPhysicalReplicationLagWarning' in alerts:
            raise SystemExit('The identical physical warning must remain excluded')
        integration = yaml.safe_load(
            (ROOT / 'scripts/tests/fixtures/postgresql-replication-alert-tests.yaml').read_text()
        )
        tests['tests'].extend(integration['tests'])
        (temp / 'rules.yml').write_text(yaml.safe_dump(rules))
    tests['rule_files'] = [str(temp / 'rules.yml')]
    (temp / 'tests.yml').write_text(yaml.safe_dump(tests))
    subprocess.run(['promtool', 'check', 'rules', str(temp / 'rules.yml')], check=True)
    subprocess.run(['promtool', 'test', 'rules', str(temp / 'tests.yml')], check=True)
    print(f'Validated {len(tests["tests"])} PostgreSQL alert scenarios')
