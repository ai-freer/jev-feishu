import unittest
from unittest.mock import Mock

from src.jev_feishu.http_client import ModelError
from src.jev_feishu.replies import ReplyGenerator
from src.jev_feishu.session import AnalysisInput, VersionStamp
from src.jev_feishu.types import ChatRef


def item():
    return AnalysisInput(VersionStamp(1, ChatRef("chat", "oc_fake"), "om_fake", None),
                         "虚构：明天几点见？", ("虚构：周三可以。",))


def answer(text="明天十点见。\n十点准时见，别迟到。"):
    return {"choices": [{"message": {"content": text}}]}


class ReplyTests(unittest.TestCase):
    def test_six_local_candidates_and_reasoning_disabled(self):
        transport = Mock(return_value=answer())
        generator = ReplyGenerator(transport=transport)
        for model in ("qwen3.5:4b", "qwen3.5:9b"):
            result = generator.generate(item(), model)
            self.assertEqual(len(result), 6)
            self.assertEqual(transport.call_count, 3 if model.endswith("4b") else 6)
            for call in transport.call_args_list:
                url, headers, payload, timeout = call.args
                self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
                self.assertEqual(payload["reasoning_effort"], "none")
                self.assertEqual(timeout, 45)

    def test_numbering_is_removed_and_invalid_output_rejected(self):
        self.assertEqual(ReplyGenerator(transport=Mock(return_value=answer("1. 明天见\n2. 十点见"))).generate(item())[:2],
                         ["明天见", "十点见"])
        for payload in (answer("只有一条"), {"choices": [{"message": {"content": "", "reasoning": "private"}}]},
                        {"choices": []}):
            with self.assertRaises(ModelError):
                ReplyGenerator(transport=Mock(return_value=payload)).generate(item())

    def test_no_remote_fallback_or_unknown_model(self):
        with self.assertRaises(ValueError):
            ReplyGenerator("https://example.com/v1")
        transport = Mock(side_effect=ModelError("connection_error"))
        with self.assertRaisesRegex(ModelError, "connection_error"):
            ReplyGenerator(transport=transport).generate(item())
        self.assertEqual(transport.call_count, 1)
        with self.assertRaises(ValueError):
            ReplyGenerator().generate(item(), "unknown")
