import unittest
from dataclasses import replace

from src.jev_feishu.viewport import VisibleMessage, visible_bubbles
from src.jev_feishu.foreground import ForegroundProbe
from tests.test_session import obs, msg, A
from tests import test_session as session_cases


class ViewportTests(unittest.TestCase):
    def test_only_complete_text_bubbles_inside_viewport(self):
        rows = [
            ("1", "顶部裁剪", False, (10, 100, 200, 1)),
            ("2", "完整消息", False, (10, 150, 200, 40)),
            ("3", "自己的消息", True, (10, 210, 200, 40)),
            ("4", "底部裁剪", False, (10, 480, 200, 50)),
            ("5", "侧栏消息", False, (600, 210, 200, 40)),
        ]
        result = visible_bubbles(rows, (0, 100, 500, 400))
        self.assertEqual([x.text for x in result], ["完整消息", "自己的消息"])

    def test_scroll_changes_epoch_even_when_bottom_message_stays_same(self):
        row = VisibleMessage("123", "虚构文字", False, 200)
        surfaces = iter([
            ("com.electron.lark", "chat", 1, "虚构", True, False, (row,)),
            ("com.electron.lark", "chat", 1, "虚构", True, False, (replace(row, top=180),)),
        ])
        probe = ForegroundProbe(lambda: next(surfaces))
        self.assertNotEqual(probe.observe().epoch, probe.observe().epoch)


class VisibleSessionTests(unittest.TestCase):
    setUp = session_cases.SessionTests.setUp
    activate = session_cases.SessionTests.activate

    def test_visible_history_uses_target_and_only_older_context(self):
        self.session.set_follow_mode("visible")
        self.session.resume()
        visible = (VisibleMessage("123", "历史问题", False, 200),)
        self.session.update_current(replace(obs(1), visible_messages=visible), A)
        self.reader.list_visible.return_value = [msg("om_old", text="历史问题"),
                                                msg("om_before", text="之前的上下文")]
        self.assertIsNone(self.session.tick())
        self.now = 1
        item = self.session.tick()
        self.assertEqual(item.stamp.message_id, "om_old")
        self.assertEqual(item.context, ("之前的上下文",))
        self.reader.list_recent.assert_not_called()
        self.session.update_current(replace(obs(2), visible_messages=()), A)
        self.assertFalse(self.session.accept_result(item.stamp, "过时回复"))

    def test_empty_view_does_not_fall_back_to_latest(self):
        self.session.set_follow_mode("visible")
        self.activate()
        self.now = 1
        self.assertIsNone(self.session.tick())
        self.reader.list_recent.assert_not_called()
        self.reader.list_visible.assert_not_called()
