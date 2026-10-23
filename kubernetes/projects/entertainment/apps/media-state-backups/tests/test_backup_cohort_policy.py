"""Bind restore-point cohort labels to actual writer images, not frozen releases."""
from copy import deepcopy
from pathlib import Path
import re
import unittest

import yaml

APP = Path(__file__).resolve().parents[1]
REPO = APP / 'proposed' if (APP / 'proposed').is_dir() else APP.parents[4]
BASE = REPO / 'kubernetes/projects'
SEMVER = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
LEGACY_CONTROLLER_IMAGES = {
    'recommender': 'registry.home/ghcr.io/abhi1693/k8s-recommendation-engine:0.3.5',
    'rack': 'registry.home/ghcr.io/abhi1693/rack-ops:0.1.3',
}


def pod(path):
    document = next(yaml.safe_load_all((BASE / path).read_text()))
    return document['spec']['template']['spec']


def container(spec, name, field='containers'):
    found = [value for value in spec.get(field, []) if value['name'] == name]
    if len(found) != 1:
        raise ValueError('expected exactly one named container')
    return found[0]


def version(image, name, immutable=False):
    digest = r'@sha256:[0-9a-f]{64}'
    suffix = digest if immutable else '(?:' + digest + ')?'
    found = re.fullmatch(re.escape('registry.home/ghcr.io/abhi1693/' + name) +
                        ':(' + SEMVER + ')' + suffix, image)
    if not found:
        raise ValueError('expected canonical semantic release image')
    return found[1]


def cohort(spec, required=True):
    initializers = spec.get('initContainers', [])
    backups = [value for value in initializers if value['name'] == 'backup-state-before-start']
    if not backups and not required:
        return None  # check_controller permits only the exact unchanged legacy images.
    if len(backups) != 1 or backups[0] is not initializers[0]:
        raise ValueError('expected exactly one first backup init')
    args = backups[0].get('args', [])
    if args.count('--cohort') != 1 or args.index('--cohort') + 1 == len(args):
        raise ValueError('expected one explicit backup cohort')
    return args[args.index('--cohort') + 1]


def check_media(qbit, ryokan):
    controller = container(qbit, 'qbittorrent-smart-queues')['image']
    reconciler = container(ryokan, 'import-reconciler')['image']
    if controller != reconciler:
        raise ValueError('qBit controller and Ryokan reconciler images differ')
    qbit_version = version(controller, 'qbittorrent-smart-queues', immutable=True)
    expected = 'qbit-' + qbit_version + '-ryokan-' + version(
        container(ryokan, 'ryokan')['image'], 'ryokan', immutable=True)
    if cohort(ryokan) != expected:
        raise ValueError('Ryokan backup cohort differs from actual writer versions')
    # The controller owns only qBit state. Retain its historical Ryokan context
    # without coupling a Ryokan-only upgrade to an unrelated controller rollout.
    own_cohort = re.escape('qbit-' + qbit_version) + '(?:-ryokan-' + SEMVER + ')?'
    if re.fullmatch(own_cohort, cohort(qbit)) is None:
        raise ValueError('qBit backup cohort differs from its own actual writer version')


def check_controller(spec, app):
    actual = cohort(spec, required=False)
    if app == 'recommender':
        main = container(spec, 'manager')['image']
        if container(spec, 'clone-home-lab', 'initContainers')['image'] != main:
            raise ValueError('Recommender clone and main images differ')
        if actual is None and main != LEGACY_CONTROLLER_IMAGES[app]:
            raise ValueError('changed Recommender images require the first backup init')
        expected = 'recommender-' + version(main, 'k8s-recommendation-engine', immutable=actual is not None)
    else:
        main = container(spec, 'rack-ops')['image']
        if actual is None and main != LEGACY_CONTROLLER_IMAGES[app]:
            raise ValueError('changed Rack image requires the first backup init')
        expected = 'rack-ops-' + version(main, 'rack-ops', immutable=actual is not None)
    if actual is not None and actual != expected:
        raise ValueError('controller backup cohort differs from actual release')


class ImageCohortContractTests(unittest.TestCase):
    def setUp(self):
        self.qbit = pod('entertainment/apps/media-qbittorrent/smart-queues-controller.yaml')
        self.ryokan = pod('entertainment/apps/media-ryokan/deployment.yaml')
        self.recommender = pod('home-automation/apps/cluster-ops/controller-manager.yaml')
        self.rack = pod('home-automation/apps/rack-ops-controllers/rack-ops-controller.yaml')

    def change_media_images(self):
        image = 'registry.home/ghcr.io/abhi1693/qbittorrent-smart-queues:0.88.99@sha256:' + 'a' * 64
        container(self.qbit, 'qbittorrent-smart-queues')['image'] = image
        container(self.ryokan, 'import-reconciler')['image'] = image
        container(self.ryokan, 'ryokan')['image'] = 'registry.home/ghcr.io/abhi1693/ryokan:1.88.99@sha256:' + 'b' * 64

    def set_cohort(self, spec, value):
        backup = container(spec, 'backup-state-before-start', 'initContainers')
        backup['args'][backup['args'].index('--cohort') + 1] = value

    def with_controller_backup(self, spec, value):
        spec['initContainers'] = [value for value in spec.get('initContainers', [])
                                  if value['name'] != 'backup-state-before-start']
        spec['initContainers'].insert(0, {'name':'backup-state-before-start', 'args':['--cohort', value]})

    def test_current_media_images_and_both_restore_cohorts_match(self):
        check_media(self.qbit, self.ryokan)

    def test_media_tag_only_writer_images_are_rejected(self):
        for target in ['qbit', 'core']:
            qbit, ryokan = deepcopy(self.qbit), deepcopy(self.ryokan)
            if target == 'qbit':
                for spec, name in [(qbit, 'qbittorrent-smart-queues'), (ryokan, 'import-reconciler')]:
                    value = container(spec, name)
                    value['image'] = value['image'].split('@')[0]
            else:
                value = container(ryokan, 'ryokan')
                value['image'] = value['image'].split('@')[0]
            with self.subTest(target=target), self.assertRaises(ValueError):
                check_media(qbit, ryokan)

    def test_backup_enabled_controllers_require_immutable_writer_images(self):
        for spec, app, name, package, prefix in [
                (self.recommender, 'recommender', 'manager', 'k8s-recommendation-engine', 'recommender-'),
                (self.rack, 'rack', 'rack-ops', 'rack-ops', 'rack-ops-')]:
            value = container(spec, name)
            tag_only = value['image'].split('@')[0]
            value['image'] = tag_only
            if app == 'recommender':
                container(spec, 'clone-home-lab', 'initContainers')['image'] = tag_only
            self.with_controller_backup(spec, prefix + version(tag_only, package))
            with self.subTest(app=app), self.assertRaises(ValueError):
                check_controller(spec, app)
            value['image'] = tag_only + '@sha256:' + 'e' * 64
            if app == 'recommender':
                container(spec, 'clone-home-lab', 'initContainers')['image'] = value['image']
            check_controller(spec, app)

    def test_each_partial_qbit_pin_update_is_rejected(self):
        for spec, name in [(self.qbit, 'qbittorrent-smart-queues'), (self.ryokan, 'import-reconciler')]:
            original = container(spec, name)['image']
            container(spec, name)['image'] = original.split('@')[0] + '@sha256:' + 'f' * 64
            with self.subTest(container=name), self.assertRaises(ValueError):
                check_media(self.qbit, self.ryokan)
            container(spec, name)['image'] = original

    def test_updated_writer_images_with_stale_either_media_cohort_are_rejected(self):
        self.change_media_images()
        expected = 'qbit-0.88.99-ryokan-1.88.99'
        stale = cohort(self.qbit)
        for spec, other in [(self.qbit, self.ryokan), (self.ryokan, self.qbit)]:
            old = stale
            self.set_cohort(other, expected)
            self.set_cohort(spec, old)
            with self.assertRaises(ValueError):
                check_media(self.qbit, self.ryokan)
            self.set_cohort(spec, expected)

    def test_new_releases_pass_when_all_writer_pins_and_cohorts_move_together(self):
        self.change_media_images()
        for spec in [self.qbit, self.ryokan]:
            self.set_cohort(spec, 'qbit-0.88.99-ryokan-1.88.99')
        check_media(self.qbit, self.ryokan)

    def test_ryokan_core_update_alone_requires_new_cohort(self):
        container(self.ryokan, 'ryokan')['image'] = 'registry.home/ghcr.io/abhi1693/ryokan:1.88.99@sha256:' + 'b' * 64
        with self.assertRaises(ValueError):
            check_media(self.qbit, self.ryokan)

    def test_ryokan_only_upgrade_preserves_controller_spec_and_historical_context(self):
        before = deepcopy(self.qbit)
        container(self.ryokan, 'ryokan')['image'] = 'registry.home/ghcr.io/abhi1693/ryokan:1.88.99@sha256:' + 'b' * 64
        actual_qbit = version(container(self.qbit, 'qbittorrent-smart-queues')['image'], 'qbittorrent-smart-queues')
        self.set_cohort(self.ryokan, 'qbit-' + actual_qbit + '-ryokan-1.88.99')
        check_media(self.qbit, self.ryokan)
        self.assertEqual(self.qbit, before)

    def test_canonical_controller_cohort_needs_only_its_own_current_version(self):
        own = version(container(self.qbit, 'qbittorrent-smart-queues')['image'], 'qbittorrent-smart-queues')
        self.set_cohort(self.qbit, 'qbit-' + own)
        check_media(self.qbit, self.ryokan)

    def test_stale_controller_own_version_and_invalid_legacy_context_are_rejected(self):
        own = version(container(self.qbit, 'qbittorrent-smart-queues')['image'], 'qbittorrent-smart-queues')
        wrong = '0.0.0' if own != '0.0.0' else '0.0.1'
        for label in ['qbit-' + wrong, 'qbit-' + wrong + '-ryokan-1.88.99',
                      'qbit-' + own + '-ryokan-latest', 'qbit-' + own + '-ryokan-1.02.3',
                      'qbit-' + own + '-ryokan-1.2.3-extra']:
            self.set_cohort(self.qbit, label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                check_media(self.qbit, self.ryokan)

    def test_cohort_is_exact_and_backup_cannot_be_missing_or_duplicated(self):
        for mutation in ['suffix', 'missing', 'duplicate']:
            changed = deepcopy(self.qbit)
            if mutation == 'suffix':self.set_cohort(changed, cohort(changed) + '-unexpected')
            elif mutation == 'missing':changed['initContainers'] = []
            else:changed['initContainers'].append(deepcopy(changed['initContainers'][0]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):check_media(changed, self.ryokan)

    def test_current_recommender_clone_and_main_are_identical(self):
        check_controller(self.recommender, 'recommender')

    def test_only_exact_legacy_controller_references_may_lack_backup_init(self):
        for original, app, name in [(self.recommender, 'recommender', 'manager'),
                                    (self.rack, 'rack', 'rack-ops')]:
            spec = deepcopy(original)
            spec['initContainers'] = [value for value in spec.get('initContainers', [])
                                      if value['name'] != 'backup-state-before-start']
            container(spec, name)['image'] = LEGACY_CONTROLLER_IMAGES[app]
            if app == 'recommender':
                container(spec, 'clone-home-lab', 'initContainers')['image'] = LEGACY_CONTROLLER_IMAGES[app]
            check_controller(spec, app)

    def test_changed_controller_tags_pins_and_registries_without_backup_are_rejected(self):
        for original, app, name, target in [
                (self.recommender, 'recommender', 'manager', '0.3.6'),
                (self.rack, 'rack', 'rack-ops', '0.1.4')]:
            legacy = LEGACY_CONTROLLER_IMAGES[app]
            for image in [legacy.rsplit(':', 1)[0] + ':' + target,
                          legacy + '@sha256:' + 'a' * 64,
                          legacy.rsplit(':', 1)[0] + ':' + target + '@sha256:' + 'b' * 64,
                          legacy.replace('registry.home/', '')]:
                spec = deepcopy(original)
                spec['initContainers'] = [value for value in spec.get('initContainers', [])
                                          if value['name'] != 'backup-state-before-start']
                container(spec, name)['image'] = image
                if app == 'recommender':
                    container(spec, 'clone-home-lab', 'initContainers')['image'] = image
                with self.subTest(app=app, image=image), self.assertRaises(ValueError):
                    check_controller(spec, app)

    def test_first_controller_release_with_immutable_pin_and_matching_first_init_passes(self):
        for original, app, name, package, target, prefix in [
                (self.recommender, 'recommender', 'manager', 'k8s-recommendation-engine', '0.3.6', 'recommender-'),
                (self.rack, 'rack', 'rack-ops', 'rack-ops', '0.1.4', 'rack-ops-')]:
            spec = deepcopy(original)
            image = 'registry.home/ghcr.io/abhi1693/' + package + ':' + target + '@sha256:' + 'c' * 64
            container(spec, name)['image'] = image
            if app == 'recommender':
                container(spec, 'clone-home-lab', 'initContainers')['image'] = image
            self.with_controller_backup(spec, prefix + target)
            check_controller(spec, app)

    def test_partial_recommender_clone_or_main_update_rejected(self):
        for name, field in [('manager', 'containers'), ('clone-home-lab', 'initContainers')]:
            changed = deepcopy(self.recommender)
            container(changed, name, field)['image'] = 'registry.home/ghcr.io/abhi1693/k8s-recommendation-engine:0.88.99@sha256:' + 'c' * 64
            with self.subTest(container=name), self.assertRaises(ValueError):check_controller(changed, 'recommender')

    def test_future_recommender_cohort_tracks_release_without_frozen_version(self):
        image = 'registry.home/ghcr.io/abhi1693/k8s-recommendation-engine:0.88.99@sha256:' + 'c' * 64
        container(self.recommender, 'manager')['image'] = image
        container(self.recommender, 'clone-home-lab', 'initContainers')['image'] = image
        self.with_controller_backup(self.recommender, 'recommender-0.88.98')
        with self.assertRaises(ValueError):check_controller(self.recommender, 'recommender')
        self.set_cohort(self.recommender, 'recommender-0.88.99')
        check_controller(self.recommender, 'recommender')

    def test_current_rack_and_future_cohort_track_actual_release(self):
        check_controller(self.rack, 'rack')
        container(self.rack, 'rack-ops')['image'] = 'registry.home/ghcr.io/abhi1693/rack-ops:0.88.99@sha256:' + 'd' * 64
        self.with_controller_backup(self.rack, 'rack-ops-0.88.98')
        with self.assertRaises(ValueError):check_controller(self.rack, 'rack')
        self.set_cohort(self.rack, 'rack-ops-0.88.99')
        check_controller(self.rack, 'rack')
