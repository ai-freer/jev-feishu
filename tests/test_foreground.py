import unittest
from unittest.mock import Mock, patch

from src.jev_feishu.foreground import ChatObservation, ForegroundProbe, _mac_surface, invalid_observation


class ForegroundTests(unittest.TestCase):
    def test_uncertain_state_carries_no_candidate(self):
        obs = invalid_observation(3, "com.electron.lark")
        self.assertEqual(obs.candidates, ())
        self.assertEqual(obs.page, "unknown")

    def test_permission_required_is_distinct_from_chat(self):
        obs = ChatObservation(1, "com.electron.lark", "permission_required", 0)
        self.assertEqual(obs.candidates, ())
        self.assertEqual(obs.page, "permission_required")

    def test_invalid_epoch_and_window_count(self):
        for epoch, windows in ((-1, 1), (1, -1), (True, 1), (1, True)):
            with self.assertRaises(ValueError):
                ChatObservation(epoch, None, "chat", windows)

    def test_epoch_changes_on_foreground_and_chat_switch(self):
        surfaces = iter([
            (None, "unknown", 0, None, False),
            ("com.electron.lark", "chat", 1, "虚构 A", True),
            ("com.electron.lark", "chat", 1, "虚构 A", True),
            ("com.electron.lark", "chat", 1, "虚构 B", True),
            ("com.electron.lark", "chat", 1, "虚构 A", True),
        ])
        probe = ForegroundProbe(lambda: next(surfaces))
        self.assertEqual([probe.observe().epoch for _ in range(5)], [1, 2, 2, 3, 4])

    def test_external_badge_participates_in_observation_epoch(self):
        surfaces = iter([
            ("com.electron.lark", "chat", 1, "虚构对象", True, None),
            ("com.electron.lark", "chat", 1, "虚构对象", True, True),
            ("com.electron.lark", "chat", 1, "虚构对象", True, True),
        ])
        probe = ForegroundProbe(lambda: next(surfaces))
        observations = [probe.observe() for _ in range(3)]
        self.assertEqual([item.epoch for item in observations], [1, 2, 2])
        self.assertEqual([item.external for item in observations], [None, True, True])

    def surface_with_badge(self, *, header_badge=False, body_badge=False, title="虚构对象"):
        import ApplicationServices as AX

        def text(value):
            return {AX.kAXRoleAttribute: "AXStaticText", AX.kAXValueAttribute: value}

        title_branch = {AX.kAXChildrenAttribute: [text(title)]}
        badge_branch = {AX.kAXChildrenAttribute: [
            {AX.kAXChildrenAttribute: [text("外部")]}
        ]} if header_badge else None
        header = {AX.kAXChildrenAttribute: [title_branch] + ([badge_branch] if badge_branch else [])}
        body = {AX.kAXChildrenAttribute: [text("外部" if body_badge else "虚构消息")]}
        composer = {AX.kAXRoleAttribute: "AXTextArea", AX.kAXValueAttribute: f"发送给 {title}"}
        pane = {AX.kAXRoleAttribute: "AXWebArea", AX.kAXTitleAttribute: "messenger-chat",
                AX.kAXChildrenAttribute: [header, body, composer]}
        window = {AX.kAXSubroleAttribute: "AXStandardWindow", AX.kAXMinimizedAttribute: False,
                  AX.kAXMainAttribute: True, AX.kAXChildrenAttribute: [pane]}
        root = {AX.kAXWindowsAttribute: [window]}
        workspace = Mock()
        workspace.frontmostApplication.return_value.bundleIdentifier.return_value = "com.electron.lark"
        with patch.object(AX, "AXIsProcessTrusted", return_value=True), \
             patch.object(AX, "AXUIElementCreateApplication", return_value=root), \
             patch.object(AX, "AXUIElementSetMessagingTimeout"), \
             patch.object(AX, "AXUIElementCopyAttributeValue", side_effect=lambda node, key, _: (0, node.get(key))):
            return _mac_surface(workspace)

    def test_external_marker_in_adjacent_header_branch_is_identity_evidence(self):
        observation = ForegroundProbe(lambda: self.surface_with_badge(header_badge=True)).observe()
        self.assertEqual(observation.page, "chat")
        self.assertIs(observation.external, True)

    def test_body_text_cannot_supply_external_identity_evidence(self):
        observation = ForegroundProbe(lambda: self.surface_with_badge(body_badge=True)).observe()
        self.assertEqual(observation.page, "chat")
        self.assertIsNone(observation.external)

    def test_chat_named_external_is_not_itself_an_identity_badge(self):
        observation = ForegroundProbe(lambda: self.surface_with_badge(title="外部")).observe()
        self.assertEqual(observation.page, "chat")
        self.assertIsNone(observation.external)

    def test_non_boolean_external_evidence_is_rejected(self):
        for flag in (0, 1, "true", "false"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                ChatObservation(1, "com.electron.lark", "chat", 1, external=flag)
