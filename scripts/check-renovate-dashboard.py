#!/usr/bin/env python3
"""Check Renovate job joins against duplicate scrape labels and retained jobs."""
import json
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'kubernetes/projects/applications/apps/renovate/grafana-dashboard.yaml'
config = yaml.safe_load(source.read_text())
dashboard = json.loads(next(iter(config['data'].values())))
panels = {panel['id']: panel for panel in dashboard['panels']}
series = []
# The newer job is shorter. Both versions of the scrape metadata coexist.
for job, start, end in [('renovate-old', 100, 400), ('renovate-new', 500, 700)]:
    for extra in ['', ',cluster_id="local",cluster_name="local"']:
        labels = f'namespace="renovate",job_name="{job}"{extra}'
        for name, value in [('kube_job_status_start_time', start),
                            ('kube_job_status_completion_time', end),
                            ('kube_job_status_succeeded', 1),
                            ('kube_job_status_failed', int(job == 'renovate-old'))]:
            series.append({'series': f'{name}{{{labels}}}', 'values': f'{value}x2'})
        series.append({'series': 'kube_job_owner{' + labels +
                       ',owner_kind="CronJob",owner_name="renovate"}', 'values': '1x2'})
checks = []
for panel_id, target, expected in [(5, 0, 1), (6, 0, 200), (9, 0, 2), (9, 1, 1)]:
    checks.append({'expr': panels[panel_id]['targets'][target]['expr'],
                   'eval_time': '1m', 'exp_samples': [{'labels': '{}', 'value': expected}]})
checks.append({'expr': panels[8]['targets'][0]['expr'], 'eval_time': '1m',
               'exp_samples': [
                   {'labels': '{namespace="renovate",job_name="renovate-old",owner_name="renovate"}', 'value': 300},
                   {'labels': '{namespace="renovate",job_name="renovate-new",owner_name="renovate"}', 'value': 200}]})
fixture = {'rule_files': [], 'evaluation_interval': '1m', 'tests': [
    {'name': 'duplicate labels preserve counts and latest duration', 'interval': '1m',
     'input_series': series, 'promql_expr_test': checks}]}
with tempfile.TemporaryDirectory(prefix='renovate-dashboard-') as directory:
    path = Path(directory) / 'tests.yaml'
    path.write_text(yaml.safe_dump(fixture))
    subprocess.run(['promtool', 'test', 'rules', str(path)], check=True)
print('Validated all five Renovate job joins with duplicate historical labels')
