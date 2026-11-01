"""Check real ethtool feature formats and reject incomplete health evidence."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('macb', Path(__file__).parents[1] / 'files/macb_network.py')
macb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(macb)


class MacbFeatureTests(unittest.TestCase):
    def test_nested_features_do_not_override_parent_state(self):
        state = macb.offloads('''Features for eth0:
scatter-gather: off
    tx-scatter-gather: off [fixed]
tcp-segmentation-offload: off
    tx-tcp-segmentation: on
''')
        self.assertEqual(state, {'scatter-gather': False, 'tcp-segmentation-offload': False})

    def test_enabled_and_fixed_formats(self):
        state = macb.offloads('scatter-gather: on\ntcp-segmentation-offload: off [fixed]\n')
        self.assertTrue(state['scatter-gather'])
        self.assertFalse(state['tcp-segmentation-offload'])

    def test_missing_and_unknown_states_fail_closed(self):
        for text in ['', 'scatter-gather: off',
                     'scatter-gather: unknown\ntcp-segmentation-offload: off']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                macb.offloads(text)


if __name__ == '__main__':
    unittest.main()
