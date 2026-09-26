import unittest

from src.jev_feishu.privacy import PrivacyGate
class PrivacyTests(unittest.TestCase):
    def test_global_default_on_and_switch_off(self):
        gate = PrivacyGate()
        self.assertTrue(gate.allows_cloud())
        gate.set_cloud(False)
        self.assertFalse(gate.allows_cloud())
        gate.set_cloud(True)
        self.assertTrue(gate.allows_cloud())

    def test_invalid_global_setting_rejected(self):
        with self.assertRaises(ValueError):
            PrivacyGate().set_cloud("yes")
        with self.assertRaises(ValueError):
            PrivacyGate(1)
