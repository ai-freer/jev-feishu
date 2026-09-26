import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.jev_feishu.config import init_app_config, load_config, save_jev_enabled
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
