import unittest
from unittest.mock import Mock, call, patch

import ApplicationServices as AX
import AppKit

from src.jev_feishu.hud import HUDController, message_preview
from src.jev_feishu import app as application


class HudFocusTests(unittest.TestCase):
    def test_main_button_rechecks_when_start_is_blocked(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock(_manual=False, _running=False, can_start=False, can_recheck=True)
        controller._render = Mock()
        with patch.object(AX, "AXIsProcessTrustedWithOptions") as prompt:
            controller.toggleRun_(None)
        controller.runtime.refresh_dependencies.assert_called_once_with()
        controller.runtime.start.assert_not_called()
        prompt.assert_not_called()

    def test_main_button_does_not_duplicate_an_inflight_check(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock(_manual=False, _running=False, can_start=False, can_recheck=False)
        controller._render = Mock()
        controller.toggleRun_(None)
        controller.runtime.refresh_dependencies.assert_not_called()
        controller.runtime.start.assert_not_called()

    def test_reply_editor_keeps_long_plain_text_scrollable_and_copyable(self):
        AppKit.NSApplication.sharedApplication()
        controller = HUDController.alloc().init()
        controller.runtime = Mock()
        controller.hint = Mock()
        scroll, field = controller._reply_editor(((0, 0), (370, 38)))
        text = "虚构长回复：" + "请先确认分工、依赖和交付范围。" * 8
        field.setString_(text)
        controller.fields = [field]
        self.assertEqual(field.string(), text)
        self.assertEqual(scroll.documentView(), field)
        self.assertTrue(scroll.hasVerticalScroller())
        self.assertTrue(field.isVerticallyResizable())
        self.assertFalse(field.isHorizontallyResizable())
        self.assertFalse(field.isRichText())
        sender = Mock()
        sender.tag.return_value = 0
        with patch.object(AppKit, "NSPasteboard") as pasteboard:
            controller.copyReply_(sender)
        pasteboard.generalPasteboard.return_value.setString_forType_.assert_called_once_with(
            text, AppKit.NSPasteboardTypeString)

    def test_message_preview_is_single_line_and_bounded(self):
        self.assertEqual(message_preview("  虚构消息\n  请确认进度  "), "虚构消息 请确认进度")
        self.assertEqual(message_preview("虚构消息内容", limit=3), "虚构消…")

    def test_reopen_restores_closed_panel_without_resuming_reading(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock()
        controller.panel = Mock()
        controller.windowWillClose_(None)

        self.assertFalse(controller.applicationShouldHandleReopen_hasVisibleWindows_(None, False))

        controller.panel.orderFrontRegardless.assert_called_once_with()
        controller.runtime.pause.assert_called_once_with()
        controller.runtime.start.assert_not_called()
        controller.runtime.set_jev_enabled.assert_not_called()

    def test_global_setting_save_failure_restores_switch(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock(jev_enabled=True)
        controller.runtime.set_jev_enabled.return_value = False
        controller.settings_info = Mock()
        controller._render = Mock()
        sender = Mock()
        sender.state.return_value = 0

        controller.toggleJev_(sender)

        controller.runtime.set_jev_enabled.assert_called_once_with(False)
        sender.setState_.assert_called_once_with(AppKit.NSControlStateValueOn)

    def test_failed_tone_change_restores_selected_tone(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock()
        controller.runtime.set_tone.return_value = False
        controller.runtime.display.return_value.tones = ("专业直接", "高情商协作", "轻松同事")
        controller._render = Mock()
        controller.hint = Mock()
        sender = Mock()
        sender.tag.return_value = 1
        sender.titleOfSelectedItem.return_value = "高情商拒绝加班"

        controller.toneChanged_(sender)

        controller.runtime.set_tone.assert_called_once_with(1, "高情商拒绝加班")
        sender.selectItemWithTitle_.assert_called_once_with("高情商协作")
        controller.hint.setStringValue_.assert_called_once_with("回复模式保存失败；选择未改变。")

    def test_app_registers_reopen_event_handler(self):
        with patch.object(application.AppKit, "NSApplication") as app_class, \
             patch.object(application, "HUDController") as hud_class, \
             patch.object(application, "AppRuntime"), \
             patch.object(application, "init_app_config"), \
             patch.object(application, "NSTimer"):
            application.main()
        app_class.sharedApplication.return_value.setDelegate_.assert_called_once_with(
            hud_class.alloc.return_value.initWithRuntime_.return_value)

    def test_editing_stays_protected_until_panel_loses_key_focus(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock()
        controller.panel = Mock()
        controller.panel.isKeyWindow.return_value = True

        controller.textDidBeginEditing_(None)
        controller.windowDidBecomeKey_(None)
        controller.textDidEndEditing_(None)
        self.assertEqual(controller.runtime.set_overlay_focused.call_args_list,
                         [call(True), call(True)])

        controller.windowDidResignKey_(None)
        self.assertEqual(controller.runtime.set_overlay_focused.call_args_list,
                         [call(True), call(True), call(False)])

    def test_tick_releases_stale_focus_after_switching_to_lark(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock(_overlay_focused=True)
        controller.panel = Mock()
        controller.settings_panel = None
        controller.panel.isKeyWindow.return_value = False
        controller._render = Mock()

        controller.tick_(None)

        controller.runtime.set_overlay_focused.assert_called_once_with(False)
        controller.runtime.pulse.assert_called_once_with()
        controller._render.assert_called_once_with(controller.runtime.display.return_value)

    def test_start_requests_accessibility_without_starting_when_untrusted(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock(_manual=False, _running=False)
        controller._render = Mock()
        with patch.object(AX, "AXIsProcessTrusted", return_value=False), \
             patch.object(AX, "AXIsProcessTrustedWithOptions") as prompt:
            controller.toggleRun_(None)
        controller.runtime.start.assert_not_called()
        prompt.assert_called_once_with({AX.kAXTrustedCheckOptionPrompt: True})

    def test_start_runs_after_accessibility_is_granted(self):
        controller = HUDController.alloc().init()
        controller.runtime = Mock(_manual=False, _running=False)
        controller._render = Mock()
        with patch.object(AX, "AXIsProcessTrusted", return_value=True), \
             patch.object(AX, "AXIsProcessTrustedWithOptions") as prompt:
            controller.toggleRun_(None)
        controller.runtime.start.assert_called_once_with()
        prompt.assert_not_called()
