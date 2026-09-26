import json
import subprocess
import unittest

from src.jev_feishu.diagnostics import Diagnostics
from src.jev_feishu.http_client import ModelError


CONFIG = {
    "reply_model": "qwen3.5:4b", "ollama_base": "http://127.0.0.1:11434/v1",
    "typesafe_base": "https://openrouter.ai/api", "typesafe_model": "~typesafe/jev-latest",
    "typesafe_key": "fake-secret-for-test",
}


def auth_ok(command, **kwargs):
    assert command[1:] == ["auth", "status", "--json", "--verify"]
    assert kwargs["shell"] is False and kwargs["timeout"] == 15
    return subprocess.CompletedProcess(command, 0, json.dumps({
        "verified": True, "identities": {"user": {"status": "ready", "openId": "ou_fixture"}}}))


class DiagnosticsTests(unittest.TestCase):
    def service(self, **kwargs):
        return Diagnostics(CONFIG, cli_lookup=lambda: "/fixture/lark-cli", runner=auth_ok,
                           get=lambda url, timeout: {"data": [{"id": "qwen3.5:4b"}]}, **kwargs)

    def test_startup_only_checks_auth_and_local_inventory(self):
        def unexpected_post(*args):
            self.fail("startup must not send model input")
        service = self.service(post=unexpected_post)
        report = service.check()
        self.assertEqual((report.cli, report.auth, report.ollama, report.jev),
                         ("ready", "ready", "ready", "configured"))
        self.assertEqual(report.own_id, "ou_fixture")
        self.assertEqual(report.available_models, ("qwen3.5:4b",))
        self.assertNotIn("ou_fixture", repr(report))
        self.assertNotIn(CONFIG["typesafe_key"], service.configuration_text("qwen3.5:9b"))
        self.assertIn("https://openrouter.ai/api/v1/systemone", service.configuration_text("qwen3.5:9b"))
        self.assertIn("qwen3.5:9b", service.configuration_text("qwen3.5:9b"))

    def test_missing_cli_and_ollama_failure_are_sanitized(self):
        def missing():
            raise FileNotFoundError("sensitive-path")
        def offline(*args):
            raise ModelError("connection_error")
        service = Diagnostics(CONFIG, cli_lookup=missing, get=offline)
        report = service.check()
        self.assertEqual((report.cli, report.auth, report.ollama, report.own_id),
                         ("missing", "unavailable", "connection_error", None))
        self.assertNotIn("sensitive", report.summary())

    def test_invalid_auth_and_missing_model_are_not_ready(self):
        service = Diagnostics(CONFIG, cli_lookup=lambda: "/fixture/lark-cli",
            runner=lambda *args, **kwargs: subprocess.CompletedProcess([], 0, '{"verified": false}'),
            get=lambda *args: {"data": []})
        report = service.check()
        self.assertEqual((report.auth, report.ollama, report.own_id),
                         ("unavailable", "model_missing", None))

    def test_connection_tests_use_only_fictional_input_and_do_not_expose_replies(self):
        requests = []
        def transport(url, headers, payload, timeout):
            requests.append((url, payload))
            if url.endswith("/systemone"):
                return {"answers": {"intent": {"choice": "闲聊", "confidence": 0.9},
                                    "risk": {"score": 0}}}
            return {"choices": [{"message": {"content": "虚构回复一\n虚构回复二"}}]}
        service = self.service(post=transport)
        cloud = service.test_connection("jev", "qwen3.5:4b")
        local = service.test_connection("ollama", "qwen3.5:9b")
        self.assertEqual((cloud.status, local.status, local.candidate_count), ("ready", "ready", 6))
        self.assertEqual(len(requests), 4)
        self.assertIn("虚构", requests[0][1]["state"])
        self.assertEqual(requests[0][1]["state"], "虚构连接测试：你好，今天过得怎么样？")
        self.assertTrue(all(p["model"] == "qwen3.5:9b" and p["reasoning_effort"] == "none"
                            for _, p in requests[1:]))
        self.assertNotIn("虚构回复", repr(local))

    def test_test_errors_return_only_known_categories(self):
        def denied(*args):
            raise ModelError("unauthorized")
        result = self.service(post=denied).test_connection("jev", "qwen3.5:4b")
        self.assertEqual(result.status, "unauthorized")
