import unittest
from unittest.mock import Mock, call, patch

import ApplicationServices as AX
import AppKit

from src.jev_feishu.hud import HUDController
from src.jev_feishu import app as application


class HudFocusTests(unittest.TestCase):
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

        controller.controlTextDidBeginEditing_(None)
        controller.windowDidBecomeKey_(None)
        controller.controlTextDidEndEditing_(None)
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
