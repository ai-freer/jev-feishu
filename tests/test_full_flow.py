from unittest.mock import Mock, patch
import unittest

from src.jev_feishu.hud import HUDController, REPLY_HINT
from tests.fixture_scenario import FixtureScenario
from tests.test_ui_state import ImmediateExecutor


class Control:
    def __init__(self):
        self.value = ""
        self.enabled = True
        self.undo = Mock()
        self.items = []

    def setStringValue_(self, value):
        self.value = value

    def stringValue(self):
        return self.value

    setTitle_ = setStringValue_
    selectItemWithTitle_ = setStringValue_
    setString_ = setStringValue_
    string = stringValue

    def scrollRangeToVisible_(self, value):
        self.visible_range = value

    def undoManager(self):
        return self.undo

    def itemTitles(self):
        return self.items

    def removeAllItems(self):
        self.items = []

    def addItemsWithTitles_(self, items):
        self.items.extend(items)

    def setEnabled_(self, value):
        self.enabled = value

    def setTextColor_(self, value):
        self.color = value

    def setToolTip_(self, value):
        self.tooltip = value


class FullFlowTests(unittest.TestCase):
    def test_verified_target_is_visible_before_generation_finishes(self):
        from dataclasses import replace
        state = replace(self.runtime.display(), status="generating", target_text="已核实的历史目标")
        with patch("ApplicationServices.AXIsProcessTrusted", return_value=True):
            self.hud._render(state)
        self.assertEqual(self.hud.source.value, "已核实的历史目标")
        self.assertTrue(all(not field.value for field in self.hud.fields))

    def setUp(self):
        self.scenario = FixtureScenario()
        self.runtime = self.scenario.make_runtime(ImmediateExecutor())
        self.hud = HUDController.alloc().init()
        self.hud.runtime = self.runtime
        self.hud._rendered_result = None
        for name in ("status", "chat", "run_button", "retry_button",
                     "model_select", "permission", "verdict", "source", "advice", "hint"):
            setattr(self.hud, name, Control())
        self.hud.fields = [Control() for _ in range(6)]
        self.hud.tone_selectors = [Control() for _ in range(3)]
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
        self.assertIn("90%", self.hud.verdict.value)
        self.assertIn("虚构验收消息 a", self.hud.source.value)
        self.assertIn("虚构验收消息 a", self.hud.source.tooltip)
        self.assertIn("下次更新时间", self.hud.advice.value)
        self.hud.fields[0].setStringValue_("虚构人工编辑内容")
        self.hud.hint.setStringValue_("已复制旧候选")
        for field in self.hud.fields:
            field.undo.reset_mock()
        self.pump()
        self.assertEqual(self.hud.fields[0].value, "虚构人工编辑内容")
        self.hud.fields[0].undo.removeAllActions.assert_not_called()
        self.scenario.switch("b")
        self.pump()
        self.assertEqual(self.hud.chat.value, "当前会话：虚构普通群 B")
        self.assertTrue(self.runtime.display().cloud_enabled)
        self.assertIn("问进度", self.hud.verdict.value)
        self.assertIn("虚构验收消息 b", self.hud.source.value)
        self.assertNotEqual(self.hud.fields[0].value, "虚构人工编辑内容")
        self.assertEqual(self.hud.hint.value, REPLY_HINT)
        for field in self.hud.fields:
            field.undo.removeAllActions.assert_called()
        self.scenario.leave()
        self.pump()
        self.assertTrue(all(not field.value for field in self.hud.fields))
        self.assertEqual(self.hud.source.value, "等待当前消息")
        self.assertIsNone(self.hud.source.tooltip)
        self.assertEqual(self.hud.advice.value, "")
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
        self.assertTrue(self.hud.run_button.enabled)
        self.assertEqual(self.hud.run_button.value, "重新检查")
        self.assertFalse(self.runtime.can_start)

    def test_main_button_recovers_auth_check_without_starting_chat_reads(self):
        self.scenario.authorized = False
        self.runtime.refresh_dependencies()
        with patch("ApplicationServices.AXIsProcessTrusted", return_value=True):
            self.hud._render(self.runtime.display())
            self.assertEqual(self.hud.run_button.value, "检查中…")
            self.assertFalse(self.hud.run_button.enabled)
            self.pump()
            self.runtime.pause()
            self.hud._render(self.runtime.display())
            self.assertIn("飞书授权不可用", self.hud.status.value)
            self.assertEqual(self.hud.run_button.value, "重新检查")
            self.assertTrue(self.hud.run_button.enabled)

            self.scenario.authorized = True
            self.hud.toggleRun_(None)
            self.assertEqual(self.hud.run_button.value, "检查中…")
            self.assertFalse(self.hud.run_button.enabled)
            self.pump()
            self.assertEqual(self.hud.run_button.value, "开始跟随")
            self.assertTrue(self.hud.run_button.enabled)
        self.assertEqual(self.runtime.display().status, "paused")
        self.assertFalse(self.runtime._running)
        self.assertEqual(self.scenario.read_count, 0)
        self.assertEqual(self.scenario.model_calls, [])

    def test_reply_service_credentials_error_is_not_mislabeled_as_jev(self):
        self.scenario.local_error = 'unauthorized'
        self.runtime.start()
        self.pump()
        self.assertEqual(self.hud.status.value, '回复服务认证失败')
        self.scenario.local_error = None
        self.scenario.cloud_error = 'unauthorized'
        self.runtime.retry_current()
        self.pump()
        self.assertIn('Jev 认证失败', self.hud.status.value)
        self.assertNotIn('本机', self.hud.status.value)

    def test_global_off_blocks_judgement_across_chat_switches(self):
        self.runtime.start()
        self.pump()
        calls = sum(kind == "jev" for kind, _ in self.scenario.model_calls)
        self.assertTrue(self.runtime.set_jev_enabled(False))
        self.pump()
        self.assertFalse(self.runtime.display().cloud_enabled)
        self.assertIn("全局关闭", self.hud.verdict.value)
        self.assertEqual(self.hud.advice.value, "")
        self.scenario.switch("b")
        self.pump()
        self.assertEqual(self.hud.chat.value, "当前会话：虚构普通群 B")
        self.assertFalse(self.runtime.display().cloud_enabled)
        self.assertEqual(sum(kind == "jev" for kind, _ in self.scenario.model_calls), calls)
        self.assertTrue(self.runtime.set_jev_enabled(True))
        self.pump()
        self.assertIn("问进度", self.hud.verdict.value)

    def test_selected_tones_are_shown_and_refreshed(self):
        self.runtime._save_tones = lambda tones: None
        self.runtime.start()
        self.pump()
        self.assertEqual([control.value for control in self.hud.tone_selectors],
                         ["专业直接", "高情商协作", "轻松同事"])
        cloud_calls = sum(kind == "jev" for kind, _ in self.scenario.model_calls)
        self.assertTrue(self.runtime.set_tone(1, "高情商拒绝加班"))
        self.pump()
        self.assertEqual(self.hud.tone_selectors[1].value, "高情商拒绝加班")
        self.assertEqual(len(self.runtime.display().result.replies), 6)
        self.assertEqual(sum(kind == "jev" for kind, _ in self.scenario.model_calls), cloud_calls)

        self.assertTrue(self.runtime.set_tone(2, "专业直接"))
        self.scenario.revision += 1
        self.pump()
        self.assertEqual(sum(kind == "jev" for kind, _ in self.scenario.model_calls), cloud_calls + 1)

    def test_returning_from_tone_menu_reuses_verified_judgment(self):
        self.runtime._save_tones = lambda tones: None
        self.runtime.start()
        self.pump()
        cloud_calls = sum(kind == "jev" for kind, _ in self.scenario.model_calls)
        self.runtime.set_overlay_focused(True)
        self.assertTrue(self.runtime.set_tone(1, "高情商拒绝加班"))
        self.runtime.set_overlay_focused(False)
        self.pump()
        self.assertEqual(self.runtime.display().tones[1], "高情商拒绝加班")
        self.assertEqual(len(self.runtime.display().result.replies), 6)
        self.assertEqual(sum(kind == "jev" for kind, _ in self.scenario.model_calls), cloud_calls)
