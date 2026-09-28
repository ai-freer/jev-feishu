import json
import unittest
from unittest.mock import Mock

from src.jev_feishu.session import AnalysisInput, VersionStamp, model_input
from src.jev_feishu.types import ChatRef
from src.jev_feishu.jev import JevJudge
from src.jev_feishu.privacy import PrivacyGate
from src.jev_feishu.replies import ReplyGenerator


class ConversationContextTests(unittest.TestCase):
    def item(self):
        return AnalysisInput(VersionStamp(1, ChatRef("chat", "oc_fixture"), "m", None),
                             "已检查，功能正常。", ("请你检查功能是否正常。", "我来检查。"),
                             ("我", "其他参与者1"), "其他参与者1", "我：请你检查功能是否正常。")

    def test_both_models_receive_speaker_roles_and_separate_target(self):
        item = self.item()
        judge_transport = Mock(return_value={"answers": {
            "intent": {"choice": "汇报进展", "confidence": 0.9}, "risk": {"score": 1}}})
        reply_transport = Mock(return_value={"choices": [{"message": {"content": "收到检查结果。\n请继续跟进其他车辆。"}}]})
        JevJudge("https://example.com", "fixture", "model", PrivacyGate(), judge_transport).judge(item)
        ReplyGenerator(transport=reply_transport).generate(item)
        decision = judge_transport.call_args.args[2]
        data = json.loads(decision["state"])
        self.assertEqual(data["reply_as"], "我")
        self.assertEqual(data["target_message"]["speaker"], "其他参与者1")
        self.assertEqual(data["previous_messages_oldest_first"][-1]["speaker"], "我")
        self.assertEqual(data["target_message"]["quoted_text"], item.target_quote)
        self.assertIn("回答问题", decision["questions"]["intent"]["criteria"])
        self.assertIn("只判断 target_message", decision["questions"]["intent"]["instructions"])
        for call in reply_transport.call_args_list:
            self.assertEqual(json.loads(call.args[2]["messages"][1]["content"]), data)

    def test_eight_messages_survive_in_chronological_order(self):
        item = AnalysisInput(self.item().stamp, "目标", tuple(f"消息{i}" for i in range(10)),
                             tuple("我" if i % 2 else "对方" for i in range(10)))
        data = model_input(item)
        rows = data["previous_messages_oldest_first"]
        self.assertEqual([r["text"] for r in rows], [f"消息{i}" for i in reversed(range(8))])
        self.assertTrue(data["context_incomplete"])

    def test_bounded_context_and_unknown_role_are_explicit(self):
        item = AnalysisInput(self.item().stamp, "目" * 9000, tuple("文" * 3000 for _ in range(8)))
        data = model_input(item)
        self.assertLessEqual(sum(len(r["text"]) + len(r["quoted_text"]) for r in data["previous_messages_oldest_first"]), 8000)
        self.assertTrue(data["context_incomplete"])
        self.assertTrue(data["target_message"]["truncated"])
        self.assertTrue(all(r["speaker"] == "发言者未确认" for r in data["previous_messages_oldest_first"]))
