"""Every tracked project application must have one parent Fleet registration."""
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import re
import subprocess
import unittest
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[4]
SOURCE = 'github.com/abhi1693/home-lab'
PARENTS = 'kubernetes/fleet/fleet-project-gitrepos'
APP_FLEET = re.compile(r'kubernetes/projects/[^/]+/apps/[^/]+/fleet\.yaml\Z')


def repository_key(value):
    if value.startswith('git@github.com:'):
        return ('github.com/' + value.split(':', 1)[1]).removesuffix('.git').lower()
    url = urlsplit(value)
    return ((url.hostname or '') + '/' + url.path.strip('/')).removesuffix('.git').lower()


def path_matches(path, pattern):
    """Component globs do not cross '/', unlike an unqualified fnmatch call."""
    left, right = PurePosixPath(path).parts, PurePosixPath(pattern).parts
    return len(left) == len(right) and all(fnmatchcase(a, b) for a, b in zip(left, right))


def registrations(tracked_files, gitrepos):
    files = {str(PurePosixPath(path)) for path in tracked_files}
    applications = sorted(str(PurePosixPath(path).parent) for path in files if APP_FLEET.fullmatch(path))
    directories = {str(parent) for path in files for parent in PurePosixPath(path).parents}
    available = files | directories
    owners = {path: [] for path in applications}
    failures = []
    for repo in gitrepos:
        if repo.get('kind') != 'GitRepo' or repository_key(repo.get('spec', {}).get('repo', '')) != SOURCE:
            continue  # Paths from another source repository cannot select local apps.
        name = repo['metadata']['name']
        paths = repo.get('spec', {}).get('paths')
        if not isinstance(paths, list) or not paths:
            failures.append(f'{name}: specify the project discovery paths')
            continue
        for pattern in paths:
            if (not isinstance(pattern, str) or not pattern or pattern.startswith('/')
                    or '..' in PurePosixPath(pattern).parts or any(c in pattern for c in '\\!^')
                    or str(PurePosixPath(pattern)) != pattern):
                failures.append(f'{name}: invalid or unsupported repository path {pattern!r}')
                continue
            # Check tracked sources, not directories left behind by a retired app.
            matches = {path for path in available if path_matches(path, pattern)}
            if not matches:
                failures.append(f'{name}: path has no tracked source: {pattern}')
            for app in applications:
                ancestors = [str(PurePosixPath(app)), *(str(x) for x in PurePosixPath(app).parents)]
                if any(path in matches for path in ancestors):
                    owners[app].append((name, pattern))
    for app, selected in owners.items():
        if len(selected) != 1:
            failures.append(f'{app}: expected one discovery path, found {len(selected)}: {selected}')
    return failures, owners


class ProjectRegistrationTest(unittest.TestCase):
    def setUp(self):
        self.app = 'kubernetes/projects/example/apps/one'
        self.files = [self.app + '/fleet.yaml']
        self.repo = {'kind': 'GitRepo', 'metadata': {'name': 'home-lab-example'},
                     'spec': {'repo': 'https://github.com/abhi1693/home-lab.git', 'paths': [self.app]}}

    def test_all_git_tracked_project_apps_have_exactly_one_parent(self):
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT, text=True).split('\0')
        docs = []
        for name in tracked:
            if name.startswith(PARENTS + '/') and name.endswith('.yaml'):
                docs.extend(x for x in yaml.safe_load_all((ROOT / name).read_text()) if x)
        failures, owners = registrations(tracked, docs)
        self.assertTrue(owners, 'No tracked project application fleet.yaml files were discovered')
        self.assertEqual(failures, [], '\n'.join(failures))

    def test_new_tracked_application_requires_registration(self):
        failures, _ = registrations(self.files + ['kubernetes/projects/example/apps/new-app/fleet.yaml'], [self.repo])
        self.assertTrue(any('new-app' in message and 'found 0' in message for message in failures))

    def test_missing_parent_path_rejects_existing_app(self):
        repo = deepcopy(self.repo)
        repo['spec']['paths'] = []
        self.assertTrue(registrations(self.files, [repo])[0])

    def test_dangling_path_is_not_satisfied_by_empty_retirement_directory(self):
        repo = deepcopy(self.repo)
        repo['spec']['paths'].append('kubernetes/projects/example/apps/retired')
        failures, _ = registrations(self.files, [repo])
        self.assertTrue(any('no tracked source' in message for message in failures))

    def test_component_glob_covers_current_and_new_apps(self):
        repo = deepcopy(self.repo)
        repo['spec']['paths'] = ['kubernetes/projects/example/apps/*']
        self.assertEqual(registrations(self.files + ['kubernetes/projects/example/apps/two/fleet.yaml'], [repo])[0], [])

    def test_duplicate_explicit_and_glob_registration_is_rejected(self):
        repo = deepcopy(self.repo)
        repo['spec']['paths'].append('kubernetes/projects/example/apps/*')
        self.assertTrue(any('found 2' in message for message in registrations(self.files, [repo])[0]))

    def test_two_parent_gitrepos_cannot_claim_the_same_app(self):
        other = deepcopy(self.repo)
        other['metadata']['name'] = 'another-parent'
        self.assertTrue(any('found 2' in message for message in registrations(self.files, [self.repo, other])[0]))

    def test_external_repository_paths_do_not_claim_local_apps(self):
        external = deepcopy(self.repo)
        external['spec']['repo'] = 'https://github.com/abhi1693/wardn-ai.git'
        self.assertEqual(registrations(self.files, [self.repo, external])[0], [])
        self.assertTrue(any('found 0' in message for message in registrations(self.files, [external])[0]))

    def test_dedicated_local_parent_and_recursive_directory_scan(self):
        repo = deepcopy(self.repo)
        repo['metadata']['name'] = 'dedicated-app-owner'
        repo['spec']['paths'] = ['kubernetes/projects/example/apps']
        self.assertEqual(registrations(self.files, [repo])[0], [])

    def test_glob_does_not_cross_directory_components(self):
        self.assertFalse(path_matches(self.app, 'kubernetes/*'))
        self.assertTrue(path_matches(self.app, 'kubernetes/projects/*/apps/*'))

    def test_ci_watches_all_project_fleet_roots_and_parent_manifests(self):
        workflow = (ROOT / '.github/workflows/infrastructure-regressions.yml').read_text()
        for path in ['kubernetes/projects/*/apps/*/fleet.yaml', PARENTS + '/*.yaml']:
            self.assertEqual(workflow.count(f'"{path}"'), 2)
