import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.jev_feishu.config import init_app_config, load_config, read_env, save_jev_enabled, save_reply_tones
from src.jev_feishu.replies import DEFAULT_TONES
from src.jev_feishu.http_client import ModelError
from src.jev_feishu.jev import JevJudge, endpoint
from src.jev_feishu.privacy import PrivacyGate
from src.jev_feishu.session import AnalysisInput, VersionStamp
from src.jev_feishu.types import ChatRef


A = ChatRef("chat", "oc_fakea")
B = ChatRef("chat", "oc_fakeb")


def item(ref=A):
    return AnalysisInput(VersionStamp(1, ref, "om_fake", None), "虚构：项目进度如何？", ("虚构：今天讨论。",))


class JevTests(unittest.TestCase):
    def test_ranking_preserves_candidate_indexes_and_respects_cloud_gate(self):
        self.transport.return_value = {"answers": {"best": {"probabilities": {"0": .8, "1": .2}}}}
        self.assertEqual(self.judge.rank_candidates(item(), ("候选一", "候选二")), (.8, .2))
        self.gate.set_cloud(False)
        self.transport.reset_mock()
        self.assertEqual(self.judge.rank_candidates(item(), ("候选一",)), ())
        self.transport.assert_not_called()

    def test_invalid_or_missing_ranking_is_not_fabricated_as_zero(self):
        for probabilities in ({}, {"0": float("nan")}, {"0": 2}, {"0": 0}):
            self.transport.return_value = {"answers": {"best": {"probabilities": probabilities}}}
            with self.assertRaises(ModelError):
                self.judge.rank_candidates(item(), ("候选一",))
    def setUp(self):
        self.gate = PrivacyGate()
        self.transport = Mock(return_value={"answers": {
            "intent": {"choice": "问进度", "confidence": 0.8},
            "risk": {"score": 2.5},
        }})
        self.judge = JevJudge("https://openrouter.ai/api", "fake-key", "~typesafe/jev-latest",
                              self.gate, self.transport)

    def test_global_default_and_off_switch(self):
        verdict = self.judge.judge(item())
        self.assertEqual((verdict.intent, verdict.risk), ("问进度", 2.5))
        args = self.transport.call_args.args
        self.assertEqual(args[0], "https://openrouter.ai/api/v1/systemone")
        self.assertEqual(args[2]["questions"]["intent"]["type"], "choice")
        self.assertEqual(args[2]["questions"]["risk"]["type"], "score")
        self.judge.judge(item(B))
        self.assertEqual(self.transport.call_count, 2)
        self.gate.set_cloud(False)
        self.assertIsNone(self.judge.judge(item()))
        self.assertIsNone(self.judge.judge(item(B)))
        self.assertEqual(self.transport.call_count, 2)

    def test_missing_key_and_malformed_response_are_sanitized(self):
        with self.assertRaisesRegex(ModelError, "not_configured"):
            JevJudge("https://openrouter.ai/api", "", "model", self.gate, self.transport).judge(item())
        for response in ({}, {"answers": {"intent": {"choice": "问进度", "confidence": 1}, "risk": {}}},
                         {"answers": {"intent": {"choice": "not-an-intent", "confidence": 1},
                                      "risk": {"score": 2}}}):
            self.transport.return_value = response
            with self.assertRaisesRegex(ModelError, "invalid_response"):
                self.judge.judge(item())

    def test_transport_errors_are_not_rewritten_with_payload(self):
        for error in ("unauthorized", "rate_limited", "connection_error"):
            self.transport.side_effect = ModelError(error)
            with self.assertRaisesRegex(ModelError, error):
                self.judge.judge(item())

    def test_base_url_composition_and_rejection(self):
        self.assertEqual(endpoint("https://openrouter.ai/api/v1"),
                         "https://openrouter.ai/api/v1/systemone")
        for value in ("http://openrouter.ai/api", "https://user:pass@openrouter.ai/api", "bad",
                      "https://openrouter.ai/api?key=secret", "https://openrouter.ai/api#secret"):
            with self.assertRaises(ValueError):
                endpoint(value)

    def test_app_config_permissions_and_typesafe_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)/"app"/"env"
            cloud = Path(tmp)/"typesafe"
            init_app_config(app)
            self.assertEqual(app.stat().st_mode & 0o777, 0o600)
            self.assertEqual(app.parent.stat().st_mode & 0o777, 0o700)
            cloud.write_text("TYPESAFE_API_KEY='fake-key'\nTYPESAFE_DEFAULT_MODEL='~typesafe/jev-latest'\n")
            cloud.chmod(0o600)
            config = load_config(app, cloud)
            self.assertEqual(config["typesafe_model"], "~typesafe/jev-latest")
            self.assertEqual(config["reply_model"], "qwen3.5:4b")
            self.assertEqual(config["reply_tones"], DEFAULT_TONES)
            self.assertTrue(config["jev_enabled"])
            self.assertNotIn("TYPESAFE_API_KEY", app.read_text())

            with app.open("a") as stream:
                stream.write("# keep this comment\nCUSTOM_SETTING='untouched value'\n")
            save_jev_enabled(False, app)
            self.assertFalse(load_config(app, cloud)["jev_enabled"])
            self.assertEqual(app.stat().st_mode & 0o777, 0o600)
            self.assertIn("CUSTOM_SETTING='untouched value'", app.read_text())
            self.assertIn("# keep this comment", app.read_text())
            save_jev_enabled(True, app)
            self.assertTrue(load_config(app, cloud)["jev_enabled"])
            self.assertEqual(app.read_text().count("JEV_FEISHU_JEV_ENABLED="), 1)

            selected = ("这事我负责", "霸道总裁", "专业对客")
            save_reply_tones(selected, app)
            self.assertEqual(load_config(app, cloud)["reply_tones"], selected)
            self.assertEqual(app.stat().st_mode & 0o777, 0o600)
            self.assertIn("CUSTOM_SETTING='untouched value'", app.read_text())
            save_reply_tones(DEFAULT_TONES, app)
            self.assertEqual(app.read_text().count("JEV_FEISHU_REPLY_TONES="), 1)

            app.write_text("JEV_FEISHU_REPLY_MODEL=qwen3.5:4b\n")
            self.assertTrue(load_config(app, cloud)["jev_enabled"])

    def test_invalid_global_setting_is_not_silently_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app" / "env"
            init_app_config(app)
            app.write_text("JEV_FEISHU_JEV_ENABLED=maybe\n")
            with self.assertRaisesRegex(ValueError, "invalid_jev_setting"):
                load_config(app, Path(tmp) / "typesafe")
            with self.assertRaises(ValueError):
                save_jev_enabled("false", app)

    def test_invalid_reply_tones_rejected_without_overwriting_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app" / "env"
            init_app_config(app)
            before = app.read_bytes()
            with self.assertRaisesRegex(ValueError, "invalid_reply_tones"):
                save_reply_tones(("unknown", *DEFAULT_TONES[1:]), app)
            self.assertEqual(app.read_bytes(), before)
            with app.open("a") as stream:
                stream.write("JEV_FEISHU_REPLY_TONES=unknown|贴吧老哥|稳如老狗\n")
            with self.assertRaisesRegex(ValueError, "invalid_reply_tones"):
                load_config(app, Path(tmp) / "typesafe")

    def test_legacy_reply_modes_migrate_without_changing_unrelated_config(self):
        mapping = {
            "高情商话术": "高情商协作", "贴吧老哥": "轻松同事", "稳如老狗": "专业直接",
            "拒绝加班": "高情商拒绝加班", "卑微乙方": "专业对客", "职场黑话": "向上同步",
            "阴阳怪气": "职场嘴替", "简短直接": "专业直接",
            "小组 Leader": "这事我负责",
        }
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app" / "env"
            cloud = Path(tmp) / "typesafe"
            init_app_config(app)
            for old, new in mapping.items():
                with self.subTest(old=old):
                    original = (f"JEV_FEISHU_REPLY_TONES='{old}|专业对客|轻松同事'\n"
                                "# keep this comment\nCUSTOM_SETTING='untouched value'\n")
                    app.write_text(original)
                    self.assertEqual(load_config(app, cloud)["reply_tones"], (new, "专业对客", "轻松同事"))
                    self.assertEqual(app.read_text(), original, "loading is read-only")
                    save_reply_tones(load_config(app, cloud)["reply_tones"], app)
                    self.assertEqual(read_env(app)["JEV_FEISHU_REPLY_TONES"], f"{new}|专业对客|轻松同事")
                    self.assertIn("# keep this comment", app.read_text())
                    self.assertIn("CUSTOM_SETTING='untouched value'", app.read_text())
                    self.assertEqual(app.stat().st_mode & 0o777, 0o600)
            app.write_text("JEV_FEISHU_REPLY_TONES=稳如老狗|简短直接|高情商话术\n")
            self.assertEqual(load_config(app, cloud)["reply_tones"],
                             ("专业直接", "专业直接", "高情商协作"))
            app.write_text("JEV_FEISHU_REPLY_TONES='轻松同事|小组 Leader|小组 Leader'\n")
            selected = load_config(app, cloud)["reply_tones"]
            self.assertEqual(selected, ("轻松同事", "这事我负责", "这事我负责"))
            save_reply_tones(selected, app)
            self.assertNotIn("小组 Leader", app.read_text())
            self.assertEqual(load_config(app, cloud)["reply_tones"], selected)
