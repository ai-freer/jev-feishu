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

    def test_internal_external_same_title_changes_observation_epoch(self):
        surfaces = iter([
            ("com.electron.lark", "chat", 1, "虚构对象", True, False),
            ("com.electron.lark", "chat", 1, "虚构对象", True, True),
            ("com.electron.lark", "chat", 1, "虚构对象", True, None),
        ])
        probe = ForegroundProbe(lambda: next(surfaces))
        self.assertEqual([probe.observe().epoch for _ in range(3)], [1, 2, 3])

    def desktop_surface(self, *, marker=None, mutate=None, body_marker=False, ax_error=False, native=False,
                        navigation=True):
        import ApplicationServices as AX

        def node(role, value=None, children=None, description=None):
            return {AX.kAXRoleAttribute: role, AX.kAXValueAttribute: value,
                    AX.kAXChildrenAttribute: children, AX.kAXDescriptionAttribute: description}

        toolbar = node("AXGroup", children=[
            node("AXButton", description="doubao avatar", children=[node("AXImage")]),
            node("AXButton", children=[node("AXImage")]), node("AXButton", children=[node("AXImage")]),
        ])
        title = node("AXStaticText", "虚构对象")
        header = node("AXGroup", children=[title, toolbar, *[
            node("AXGroup", children=[node("AXImage"), node("AXStaticText", caption)])
            for caption in ("消息", "云文档", "文件")], node("AXImage")])
        if marker is not None:
            header[AX.kAXChildrenAttribute].insert(1, node("AXGroup", children=[node("AXStaticText", marker)]))
        if native:
            def wrap(child, levels=1):
                for _ in range(levels):
                    child = node("AXGroup", children=[child])
                return child
            buttons = [wrap(node("AXButton", children=[node("AXImage", children=[])])) for _ in range(5)]
            buttons[0][AX.kAXChildrenAttribute][0][AX.kAXTitleAttribute] = "doubao avatar"
            buttons.append(node("AXGroup", children=[
                wrap(node("AXButton", children=[node("AXImage", children=[])]), 3),
                wrap(node("AXButton", children=[node("AXImage", children=[])]), 3),
            ]))
            tabs = [node("AXGroup", children=[node("AXImage", children=[]), wrap(node("AXStaticText", caption, children=[]))])
                    for caption in ("消息", "云文档", "文件")]
            tabs.extend(wrap(node("AXImage", children=[]), 2) for _ in range(2))
            badge = node("AXGroup", children=[]) if marker is None else node("AXStaticText", marker, children=[])
            header = node("AXGroup", children=[
                wrap(node("AXGroup", children=[]), 3), wrap(title), wrap(badge),
                wrap(node("AXGroup", children=buttons)), node("AXGroup", children=tabs),
            ])
            if not navigation:
                header[AX.kAXChildrenAttribute].pop()
        if mutate:
            mutate(header)
        pane = node("AXWebArea", children=[
            node("AXGroup", children=[header]),
            node("AXGroup", children=[node("AXStaticText", "外部" if body_marker else "虚构正文")]),
            node("AXTextArea", "发送给 虚构对象"),
        ])
        pane[AX.kAXTitleAttribute] = "messenger-chat"
        window = node("AXWindow", children=[pane])
        window.update({AX.kAXSubroleAttribute: "AXStandardWindow", AX.kAXMinimizedAttribute: False,
                       AX.kAXMainAttribute: True})
        root = {AX.kAXWindowsAttribute: [window]}
        def read(node, key, _):
            if ax_error and node is header[children_key][-1] and key == AX.kAXChildrenAttribute:
                return AX.kAXErrorCannotComplete, None
            return 0, node.get(key)
        children_key = AX.kAXChildrenAttribute
        workspace = Mock()
        workspace.frontmostApplication.return_value.bundleIdentifier.return_value = "com.electron.lark"
        with patch.object(AX, "AXIsProcessTrusted", return_value=True), \
             patch.object(AX, "AXUIElementCreateApplication", return_value=root), \
             patch.object(AX, "AXUIElementSetMessagingTimeout"), \
             patch.object(AX, "AXUIElementCopyAttributeValue", side_effect=read):
            return _mac_surface(workspace)

    def test_complete_desktop_header_distinguishes_internal_and_external(self):
        self.assertIs(self.desktop_surface()[-1], False)
        self.assertIs(self.desktop_surface(marker="外部")[-1], True)
        self.assertIs(self.desktop_surface(body_marker=True)[-1], False)

    def test_native_wrapped_header_distinguishes_internal_and_external(self):
        self.assertIs(self.desktop_surface(native=True)[-1], False)
        self.assertIs(self.desktop_surface(native=True, marker="外部")[-1], True)
        self.assertIs(self.desktop_surface(native=True, body_marker=True)[-1], False)

    def test_native_header_without_navigation_distinguishes_internal_and_external(self):
        self.assertIs(self.desktop_surface(native=True, navigation=False)[-1], False)
        self.assertIs(self.desktop_surface(native=True, navigation=False, marker="外部")[-1], True)
        self.assertIs(self.desktop_surface(native=True, navigation=False, body_marker=True)[-1], False)

    def test_incomplete_header_without_navigation_remains_unknown(self):
        import ApplicationServices as AX
        children = AX.kAXChildrenAttribute
        for mutate in (lambda h: h[children][2].update({children: None}),
                       lambda h: h[children].pop(2),
                       lambda h: h[children][3].update({children: []})):
            self.assertIsNone(self.desktop_surface(native=True, navigation=False, mutate=mutate)[-1])
        self.assertIsNone(self.desktop_surface(native=True, navigation=False, marker="未知徽标")[-1])
        self.assertIsNone(self.desktop_surface(native=True, navigation=False, ax_error=True)[-1])

    def test_native_header_missing_badge_slot_or_read_failure_remains_unknown(self):
        import ApplicationServices as AX
        children = AX.kAXChildrenAttribute
        for mutate in (lambda h: h[children][2].update({children: None}),
                       lambda h: h[children].pop(2),
                       lambda h: h[children][4][children].pop(1)):
            self.assertIsNone(self.desktop_surface(native=True, mutate=mutate)[-1])
        self.assertIsNone(self.desktop_surface(native=True, marker="未知徽标")[-1])
        self.assertIsNone(self.desktop_surface(native=True, ax_error=True)[-1])
        def deeper_than_supported(header):
            toolbar = header[children][3]
            for _ in range(9):
                toolbar = {AX.kAXRoleAttribute: "AXGroup", children: [toolbar]}
            header[children][3] = toolbar
        self.assertIsNone(self.desktop_surface(native=True, mutate=deeper_than_supported)[-1])

    def test_complete_header_and_api_scope_resolve_internal_external_namesakes(self):
        import json
        import subprocess
        from src.jev_feishu.chat_resolver import ChatResolver, LarkIdentityLookup
        from src.jev_feishu.types import ChatRef

        def result(**data):
            return subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "data": data}), "")

        for marker, expected, layout in (
                (marker, expected, layout)
                for marker, expected in ((None, "oc_internal"), ("外部", "oc_external"))
                for layout in ({}, {"native": True, "navigation": False})):
            with self.subTest(marker=marker, layout=layout):
                observation = ForegroundProbe(lambda: self.desktop_surface(marker=marker, **layout)).observe()
                runner = Mock(side_effect=[result(users=[
                    {"localized_name": "虚构对象", "p2p_chat_id": "oc_internal", "is_cross_tenant": False},
                    {"localized_name": "虚构对象", "p2p_chat_id": "oc_external", "is_cross_tenant": True},
                ], has_more=False), result(chats=None, has_more=False)])
                self.assertEqual(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observation)),
                                 ChatRef("chat", expected))

    def test_unknown_or_incomplete_header_is_not_internal_evidence(self):
        import ApplicationServices as AX
        children = AX.kAXChildrenAttribute
        cases = (
            lambda h: h[children].pop(),
            lambda h: h[children][1].update({children: None}),
            lambda h: h[children][2].update({children: None}),
            lambda h: h[children][2][children][1].update({AX.kAXValueAttribute: None}),
            lambda h: h[children][1][children][0].update({AX.kAXDescriptionAttribute: "unknown"}),
            lambda h: h[children][3][children][1].update({AX.kAXValueAttribute: "unknown tab"}),
            lambda h: h[children].append({AX.kAXRoleAttribute: "AXGroup", children: []}),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.assertIsNone(self.desktop_surface(mutate=mutate)[-1])
        self.assertIsNone(self.desktop_surface(marker="未知身份标记")[-1])
        self.assertIsNone(self.desktop_surface(ax_error=True)[-1])

    def test_oversized_and_deep_header_cannot_be_assumed_internal(self):
        import ApplicationServices as AX
        children = AX.kAXChildrenAttribute
        def oversized(header):
            header[children][1][children] *= 5
        def too_deep(header):
            part = header[children][1]
            for _ in range(6):
                part = {AX.kAXRoleAttribute: "AXGroup", children: [part]}
            header[children][1] = part
        for mutate in (oversized, too_deep):
            self.assertIsNone(self.desktop_surface(mutate=mutate)[-1])

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
