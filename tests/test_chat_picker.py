import unittest

from src.jev_feishu.chat_picker import parse_manual_ref


class ChatPickerTests(unittest.TestCase):
    def test_explicit_reference_parsing(self):
        self.assertEqual(parse_manual_ref(" oc_fake ").kind, "chat")
        self.assertEqual(parse_manual_ref(" ou_fake ").kind, "user")
        for invalid in ("", "abc", "oc_", "oc_bad space"):
            with self.assertRaises(ValueError):
                parse_manual_ref(invalid)
