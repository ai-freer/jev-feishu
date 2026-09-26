from unittest.mock import patch
import unittest

from src.jev_feishu.hud import HUDController
from tests.fixture_scenario import FixtureScenario
from tests.test_ui_state import ImmediateExecutor


class Control:
    def __init__(self):
        self.value = ""
        self.enabled = True

    def setStringValue_(self, value):
        self.value = value

    def stringValue(self):
        return self.value

    setTitle_ = setStringValue_
    selectItemWithTitle_ = setStringValue_

    def setEnabled_(self, value):
        self.enabled = value


class FullFlowTests(unittest.TestCase):
    def setUp(self):
        self.scenario = FixtureScenario()
        self.runtime = self.scenario.make_runtime(ImmediateExecutor())
        self.hud = HUDController.alloc().init()
        self.hud.runtime = self.runtime
        self.hud._rendered_result = None
        for name in ("status", "chat", "run_button", "retry_button",
                     "model_select", "permission", "verdict", "hint"):
            setattr(self.hud, name, Control())
        self.hud.fields = [Control() for _ in range(6)]
        self.addCleanup(self.scenario.close)
        self.addCleanup(self.runtime.close)

    def pump(self):
        for _ in range(3):
            self.runtime.pulse()
        with patch("ApplicationServices.AXIsProcessTrusted", return_value=True):
            self.hud._render(self.runtime.display())

    def test_real_adapters_to_six_rendered_fields_and_switch_clear(self):
        self.runtime.start()
        self.pump()
        self.assertEqual(self.hud.chat.value, "当前会话：虚构单聊 A")
        self.assertEqual(sum(bool(field.value) for field in self.hud.fields), 6)
        self.assertTrue(any(kind == "jev" for kind, model in self.scenario.model_calls))
        self.assertIn("问进度", self.hud.verdict.value)
        self.hud.fields[0].setStringValue_("虚构人工编辑内容")
        self.pump()
        self.assertEqual(self.hud.fields[0].value, "虚构人工编辑内容")
        self.scenario.switch("b")
        self.pump()
        self.assertEqual(self.hud.chat.value, "当前会话：虚构普通群 B")
        self.assertTrue(self.runtime.display().cloud_enabled)
        self.assertIn("问进度", self.hud.verdict.value)
        self.assertNotEqual(self.hud.fields[0].value, "虚构人工编辑内容")
        self.scenario.leave()
        self.pump()
        self.assertTrue(all(not field.value for field in self.hud.fields))
        self.assertFalse(self.hud.retry_button.enabled)

    def test_errors_and_auth_expiry_remain_visible_without_old_candidates(self):
        self.runtime.start()
        self.pump()
        self.scenario.local_error = "connection_error"
        self.runtime.retry_current()
        self.pump()
        self.assertIn("模型连接失败", self.hud.status.value)
        self.assertTrue(all(not field.value for field in self.hud.fields))
        self.scenario.authorized = False
        self.runtime.refresh_dependencies()
        self.pump()
        self.assertIn("飞书授权不可用", self.hud.status.value)
        self.assertFalse(self.hud.run_button.enabled)

    def test_global_off_blocks_judgement_across_chat_switches(self):
        self.runtime.start()
        self.pump()
        calls = sum(kind == "jev" for kind, _ in self.scenario.model_calls)
        self.assertTrue(self.runtime.set_jev_enabled(False))
        self.pump()
        self.assertFalse(self.runtime.display().cloud_enabled)
        self.assertIn("全局关闭", self.hud.verdict.value)
        self.scenario.switch("b")
        self.pump()
        self.assertEqual(self.hud.chat.value, "当前会话：虚构普通群 B")
        self.assertFalse(self.runtime.display().cloud_enabled)
        self.assertEqual(sum(kind == "jev" for kind, _ in self.scenario.model_calls), calls)
        self.assertTrue(self.runtime.set_jev_enabled(True))
        self.pump()
        self.assertIn("问进度", self.hud.verdict.value)
