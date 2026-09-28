import unittest
from dataclasses import replace

from src.jev_feishu.viewport import VisibleMessage, visible_bubbles, bubble_text
from src.jev_feishu.foreground import ForegroundProbe
from tests.test_session import obs, msg, A
from tests import test_session as session_cases


class ViewportTests(unittest.TestCase):
    def test_quote_and_reaction_do_not_hide_plain_text_body(self):
        rich = {"AXDOMClassList": ["richTextContainer"]}
        body = {"AXRole": "AXStaticText", "AXValue": "真实正文"}
        quote = {"AXRole": "AXStaticText", "AXValue": "引用标题"}
        reaction = {"AXRole": "AXImage"}
        read = lambda node, key: node.get(key)
        self.assertEqual(bubble_text([quote, rich, body, reaction], read,
                                    lambda root, limit: [root, body]), "真实正文")

    def test_body_image_is_not_mistaken_for_complete_text(self):
        rich = {"AXDOMClassList": ["richTextContainer"]}
        image = {"AXRole": "AXImage"}
        body = {"AXRole": "AXStaticText", "AXValue": "图片说明"}
        self.assertEqual(bubble_text([rich, body, image], lambda n, k: n.get(k),
                                    lambda root, limit: [root, body, image]), "")

    def test_bottom_unsupported_bubble_is_preserved_as_an_anchor(self):
        result = visible_bubbles([
            ("1", "上方可处理文字", False, (10, 150, 200, 40)),
            ("2", "", False, (10, 250, 200, 80)),
        ], (0, 100, 500, 400))
        self.assertEqual(result[-1].token, "2")
        self.assertEqual(result[-1].text, "")

    def test_bottom_partial_bubble_remains_the_target(self):
        rows = [
            ("1", "顶部裁剪", False, (10, 100, 200, 1)),
            ("2", "完整消息", False, (10, 150, 200, 40)),
            ("3", "自己的消息", True, (10, 210, 200, 40)),
            ("4", "底部裁剪", False, (10, 480, 200, 50)),
            ("5", "侧栏消息", False, (600, 210, 200, 40)),
        ]
        result = visible_bubbles(rows, (0, 100, 500, 400))
        self.assertEqual([x.text for x in result], ["完整消息", "自己的消息", "底部裁剪"])

    def test_position_only_scroll_does_not_restart_generation(self):
        row = VisibleMessage("123", "虚构文字", False, 200)
        surfaces = iter([
            ("com.electron.lark", "chat", 1, "虚构", True, False, (row,)),
            ("com.electron.lark", "chat", 1, "虚构", True, False, (replace(row, top=180),)),
        ])
        probe = ForegroundProbe(lambda: next(surfaces))
        self.assertEqual(probe.observe().epoch, probe.observe().epoch)

    def test_visible_content_change_invalidates_generation(self):
        row = VisibleMessage("123", "虚构文字", False, 200)
        surfaces = iter([
            ("com.electron.lark", "chat", 1, "虚构", True, False, (row,)),
            ("com.electron.lark", "chat", 1, "虚构", True, False, (replace(row, text="修改后"),)),
        ])
        probe = ForegroundProbe(lambda: next(surfaces))
        self.assertNotEqual(probe.observe().epoch, probe.observe().epoch)


class VisibleSessionTests(unittest.TestCase):
    setUp = session_cases.SessionTests.setUp
    activate = session_cases.SessionTests.activate

    def test_visible_history_uses_target_and_only_older_context(self):
        self.session.set_follow_mode("visible")
        self.session.resume()
        visible = (VisibleMessage("122", "之前的上下文", True, 100),
                   VisibleMessage("123", "历史问题", False, 200))
        self.session.update_current(replace(obs(1), visible_messages=visible), A)
        self.reader.list_visible.return_value = [msg("om_old", text="历史问题"),
                                                msg("om_before", text="之前的上下文")]
        self.assertIsNone(self.session.tick())
        self.now = 1
        item = self.session.tick()
        self.assertEqual(item.stamp.message_id, "123")
        self.assertEqual(self.session.target_text, "历史问题")
        self.assertEqual(item.context, ("之前的上下文",))
        self.assertEqual(item.context_senders, ("我",))
        self.reader.list_recent.assert_not_called()
        self.reader.list_visible.assert_not_called()
        self.session.update_current(replace(obs(2), visible_messages=()), A)
        self.assertEqual(self.session.target_text, "")
        self.assertFalse(self.session.accept_result(item.stamp, "过时回复"))

    def test_eight_visible_context_messages_keep_roles_and_quote(self):
        self.session.set_follow_mode("visible")
        self.session.resume()
        rows = tuple(VisibleMessage(str(i), f"前文{i}", i % 2 == 0, i * 30) for i in range(8))
        target = VisibleMessage("8", "已完成核查", False, 300, "回复我：请核查一下")
        self.session.update_current(replace(obs(1), visible_messages=(*rows, target)), A)
        self.now = 1
        item = self.session.tick()
        self.assertEqual(len(item.context), 8)
        self.assertEqual(item.context[-1], "前文0")
        self.assertEqual(item.context_senders[-1], "我")
        self.assertEqual(item.target_quote, "回复我：请核查一下")
        self.reader.list_recent.assert_not_called()

    def test_short_repeated_text_needs_no_api_matching(self):
        self.session.set_follow_mode("visible")
        self.session.resume()
        self.session.update_current(replace(obs(1), visible_messages=(
            VisibleMessage("1", "好", False, 100),
            VisibleMessage("2", "好", False, 200),
        )), A)
        self.now = 1
        item = self.session.tick()
        self.assertEqual(item.text, "好")
        self.assertEqual(item.stamp.message_id, "2")
        self.reader.list_visible.assert_not_called()
        self.reader.list_recent.assert_not_called()
        self.assertIsNone(self.session.tick())

    def test_bottom_own_or_unsupported_never_falls_back(self):
        for text, own, status in (("自己的话", True, "viewport_own"), ("", False, "viewport_nontext")):
            self.setUp()
            self.session.set_follow_mode("visible")
            self.session.resume()
            self.session.update_current(replace(obs(1), visible_messages=(
                VisibleMessage("1", "上方文字", False, 100),
                VisibleMessage("2", text, own, 200),
            )), A)
            self.now = 1
            self.assertIsNone(self.session.tick())
            self.assertEqual(self.session.read_status, status)
            self.reader.list_recent.assert_not_called()
            self.reader.list_visible.assert_not_called()

    def test_empty_view_does_not_fall_back_to_latest(self):
        self.session.set_follow_mode("visible")
        self.activate()
        self.now = 1
        self.assertIsNone(self.session.tick())
        self.reader.list_recent.assert_not_called()
        self.reader.list_visible.assert_not_called()
