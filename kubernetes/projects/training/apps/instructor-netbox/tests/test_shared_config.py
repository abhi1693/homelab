"""Shared defaults must support independent instance overrides without drift."""
import importlib.util
from pathlib import Path
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'scripts/render-training-netbox.py').exists())
SPEC = importlib.util.spec_from_file_location('training_renderer', ROOT / 'scripts/render-training-netbox.py')
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


class SharedConfigurationTests(unittest.TestCase):
    def test_nested_override_preserves_other_defaults_and_instances(self):
        defaults = {'resources': {'requests': {'cpu': '250m', 'memory': '1536Mi'}}, 'hosts': ['default']}
        student = RENDERER.merge(defaults, {'resources': {'requests': {'cpu': '100m'}}, 'hosts': ['student']})
        instructor = RENDERER.merge(defaults, {})
        self.assertEqual(student['resources']['requests'], {'cpu': '100m', 'memory': '1536Mi'})
        self.assertEqual(student['hosts'], ['student'])
        student['resources']['requests']['memory'] = '1Gi'
        self.assertEqual(instructor, defaults)
        self.assertEqual(defaults['hosts'], ['default'])

    def test_explicit_null_and_empty_list_replace_defaults(self):
        self.assertEqual(RENDERER.merge({'a': {'b': 1}, 'list': [1]}, {'a': None, 'list': []}), {'a': None, 'list': []})

    def test_checked_in_instances_match_sources(self):
        RENDERER.render(check=True)


if __name__ == '__main__':
    unittest.main()
