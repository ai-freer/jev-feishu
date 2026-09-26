import json
import subprocess
import unittest
from unittest.mock import Mock

from src.jev_feishu.lark_reader import LarkReader, ReaderError, parse_messages
from src.jev_feishu.types import ChatRef


def message(**changes):
    item = dict(message_id="om_fake", msg_type="text", create_time="1000",
                deleted=False, updated=False, sender={"id": "ou_fake"}, content="虚构测试消息")
    item.update(changes)
    return item


def envelope(*items):
    return {"ok": True, "identity": "user", "data": {"messages": list(items)}}


class LarkReaderTests(unittest.TestCase):
    def test_text_and_edit(self):
        result = parse_messages(envelope(message(updated=True, update_time="2000")))
        self.assertEqual(result[0].text, "虚构测试消息")
        self.assertEqual(result[0].update_time, "2000")
        self.assertNotIn("虚构", repr(result[0]))

    def test_recall_discards_text_and_retains_tombstone(self):
        result = parse_messages(envelope(message(deleted=True, sender=None)))
        self.assertTrue(result[0].deleted)
        self.assertEqual((result[0].text, result[0].sender_id), ("", ""))

    def test_nontext_threads_and_blank_text_are_excluded(self):
        items = [message(msg_type=t) for t in ("post", "image", "file", "interactive")]
        items += [message(thread_id="omt_fake", thread_replies=[message()]), message(content=" ")]
        self.assertEqual(parse_messages(envelope(*items)), [])

    def test_latest_nontext_does_not_expose_older_text(self):
        self.assertEqual(parse_messages(envelope(message(msg_type="image"),
                                                message(message_id="om_older"))), [])

    def test_latest_thread_or_blank_text_does_not_reactivate_older_message(self):
        for changes in ({"thread_id": "omt_fake"}, {"content": " \n "}):
            with self.subTest(changes=changes):
                self.assertEqual(parse_messages(envelope(message(**changes),
                                    message(message_id="om_older"))), [])

    def test_missing_or_malformed_fields_fail_closed(self):
        for key in ("message_id", "sender", "content", "create_time", "deleted", "msg_type", "updated"):
            item = message()
            del item[key]
            with self.subTest(key=key), self.assertRaises(ReaderError):
                parse_messages(envelope(item))
        for changes in ({"deleted": "false"}, {"updated": "false"}, {"content": {}}, {"update_time": 1},
                        {"updated": True}, {"sender": {"id": None}}):
            with self.subTest(changes=changes), self.assertRaises(ReaderError):
                parse_messages(envelope(message(**changes)))

    def test_envelope_rejects_failure_wrong_identity_and_missing_messages(self):
        for value in ({"ok": False}, [], {"ok": True, "identity": "bot"},
                      {"ok": True, "identity": "user", "data": {}}):
            with self.subTest(value=value), self.assertRaises(ReaderError):
                parse_messages(value)

    def test_command_is_bounded_user_read_without_shell(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(envelope(message())), ""))
        reader = LarkReader(runner)
        for kind, value, flag in (("chat", "oc_fake", "--chat-id"), ("user", "ou_fake", "--user-id")):
            self.assertEqual(len(reader.list_recent(ChatRef(kind, value))), 1)
            args, kwargs = runner.call_args
            self.assertIn(flag, args[0])
            self.assertEqual(args[0][args[0].index("--as") + 1], "user")
            self.assertNotIn("--page-all", args[0])
            self.assertNotIn("--download-resources", args[0])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["timeout"], 15)

    def test_cli_errors_do_not_echo_sensitive_output(self):
        for outcome in (subprocess.CompletedProcess([], 1, "private payload", "private payload"),
                        subprocess.CompletedProcess([], 0, "private payload", ""),
                        subprocess.TimeoutExpired("private payload", 15, output="private payload"),
                        FileNotFoundError("private payload")):
            runner = Mock()
            if isinstance(outcome, Exception):
                runner.side_effect = outcome
            else:
                runner.return_value = outcome
            with self.assertRaises(ReaderError) as caught:
                LarkReader(runner).list_recent(ChatRef("chat", "oc_fake"))
            self.assertNotIn("private", str(caught.exception))

    def test_invalid_reference_and_page_size_do_not_call_cli(self):
        for kind, value in (("other", "oc_fake"), ("chat", "oc_"), ("chat", "oc_x\n"), ("user", "oc_fake")):
            with self.assertRaises(ValueError):
                ChatRef(kind, value)
        runner = Mock()
        for limit in (0, 51, True, "10"):
            with self.assertRaises(ValueError):
                LarkReader(runner).list_recent(ChatRef("chat", "oc_fake"), limit)
        runner.assert_not_called()
