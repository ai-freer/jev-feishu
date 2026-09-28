import unittest
from unittest.mock import Mock

from src.jev_feishu.foreground import ChatEvidence, ChatObservation
from src.jev_feishu.lark_reader import ReaderError
from src.jev_feishu.session import SessionController
from src.jev_feishu.types import ChatRef, TextMessage


LARK = "com.electron.lark"
A = ChatRef("chat", "oc_fakea")
B = ChatRef("chat", "oc_fakeb")


def obs(epoch, ref=A, bundle=LARK, page="chat"):
    evidence = () if ref is None else (ChatEvidence(ref, True, True),)
    return ChatObservation(epoch, bundle, page, 1, evidence, "虚构会话", True)


def msg(identifier="om_fake", sender="ou_other", text="虚构消息", update=None, deleted=False):
    return TextMessage(identifier, sender, text, "1000", update, deleted)


class SessionTests(unittest.TestCase):
    def test_api_context_preserves_eight_messages_and_distinct_senders(self):
        self.activate()
        self.reader.list_recent.return_value = [msg("target", "ou_other", "已核查正常")] + [
            msg(f"old{i}", "ou_self" if i % 2 else "ou_third", f"前文{i}") for i in range(9)]
        item = self.session.tick()
        self.assertEqual(len(item.context), 8)
        self.assertEqual(item.target_sender, "其他参与者1")
        self.assertEqual(item.context_senders[0], "其他参与者2")
        self.assertEqual(item.context_senders[1], "我")
        self.assertNotIn("前文8", item.context)

    def setUp(self):
        self.now = 0.0
        self.reader = Mock()
        self.reader.list_recent.return_value = [msg()]
        self.session = SessionController(self.reader, "ou_self", lambda: self.now)

    def activate(self, epoch=1, ref=A):
        self.session.resume()
        self.session.update_current(obs(epoch, ref), ref)

    def test_default_pause_and_unverified_observation_never_read(self):
        self.session.update_current(obs(1), A)
        self.assertIsNone(self.session.tick())
        self.session.resume()
        self.session.update_current(obs(2, None), A)
        self.assertIsNone(self.session.tick())
        self.reader.list_recent.assert_not_called()

    def test_current_chat_dedup_and_context(self):
        self.reader.list_recent.return_value = [msg(), msg("om_older", "ou_self", "自己的上一句")]
        self.activate()
        analysis = self.session.tick()
        self.assertEqual(analysis.text, "虚构消息")
        self.assertEqual(analysis.context, ("自己的上一句",))
        self.assertTrue(self.session.accept_result(analysis.stamp, "虚构候选"))
        self.now = 3
        self.assertIsNone(self.session.tick())
        self.assertEqual(self.session.candidate, "虚构候选")

    def test_own_message_looks_back_and_preserves_following_reply(self):
        self.reader.list_recent.return_value = [msg(sender="ou_self"), msg("om_older")]
        self.activate()
        item = self.session.tick()
        self.assertEqual(item.stamp.message_id, "om_older")
        self.assertEqual(item.following_self, ("虚构消息",))

    def test_own_reply_or_new_unsupported_message_clears_old_candidate(self):
        self.activate()
        first = self.session.tick()
        self.session.accept_result(first.stamp, "旧候选")
        self.reader.list_recent.return_value = [msg("om_own", "ou_self"), msg()]
        self.now = 3
        updated = self.session.tick()
        self.assertTrue(updated.following_self)
        self.assertFalse(self.session.is_current(first.stamp))
        self.assertIsNone(self.session.candidate)
        self.reader.list_recent.return_value = []
        self.now = 6
        self.assertIsNone(self.session.tick())

    def test_switch_and_return_reject_old_result(self):
        self.activate(1)
        old = self.session.tick()
        self.session.update_current(obs(2, None), None)
        self.assertIsNone(self.session.candidate)
        self.session.update_current(obs(3, B), B)
        self.now = 3
        new = self.session.tick()
        self.session.update_current(obs(4, A), A)
        self.assertFalse(self.session.accept_result(old.stamp, "stale"))
        self.assertFalse(self.session.accept_result(new.stamp, "stale"))
        self.assertIsNone(self.session.candidate)

    def test_leaving_lark_pauses_and_clears(self):
        self.activate()
        item = self.session.tick()
        self.session.accept_result(item.stamp, "候选")
        self.session.update_current(obs(2, A, "other"), None)
        self.assertIsNone(self.session.current_ref)
        self.assertIsNone(self.session.candidate)
        self.now = 3
        self.assertIsNone(self.session.tick())

    def test_edit_and_recall_invalidate_result(self):
        self.activate()
        item = self.session.tick()
        self.session.accept_result(item.stamp, "候选")
        self.reader.list_recent.return_value = [msg(update="2000")]
        self.now = 3
        updated = self.session.tick()
        self.assertIsNone(self.session.candidate)
        self.assertEqual(updated.stamp.update_time, "2000")
        self.assertFalse(self.session.accept_result(item.stamp, "旧候选"))
        self.session.accept_result(updated.stamp, "新候选")
        self.reader.list_recent.return_value = [msg(deleted=True, text="")]
        self.now = 6
        self.assertIsNone(self.session.tick())
        self.assertIsNone(self.session.candidate)

    def test_inflight_read_discarded_after_switch(self):
        self.activate()
        def switch(_):
            self.session.update_current(obs(2, B), B)
            return [msg()]
        self.reader.list_recent.side_effect = switch
        self.assertIsNone(self.session.tick())
        self.assertIsNone(self.session.candidate)

    def test_overlay_focus_preserves_candidate_but_blocks_reads(self):
        self.activate()
        item = self.session.tick()
        self.session.accept_result(item.stamp, "可编辑")
        self.session.set_overlay_focused(True)
        self.session.update_current(obs(2, A, "assistant"), None)
        self.assertEqual(self.session.candidate, "可编辑")
        self.now = 3
        self.assertIsNone(self.session.tick())
        self.session.set_overlay_focused(False)
        self.assertIsNone(self.session.candidate)

    def test_read_finishing_during_edit_does_not_clear_candidate(self):
        self.activate()
        item = self.session.tick()
        self.session.accept_result(item.stamp, "正在编辑")
        def begin_edit(_):
            self.session.set_overlay_focused(True)
            return [msg("om_new")]
        self.reader.list_recent.side_effect = begin_edit
        self.now = 3
        self.assertIsNone(self.session.tick())
        self.assertEqual(self.session.candidate, "正在编辑")

    def test_error_backoff_caps_at_sixty(self):
        self.activate()
        self.reader.list_recent.side_effect = ReaderError("cli_error")
        for delay in (3, 6, 12, 24, 48, 60):
            self.assertIsNone(self.session.tick())
            next_time = self.session._next_poll
            self.assertEqual(next_time - self.now, delay)
            self.now = next_time
