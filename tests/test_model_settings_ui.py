from concurrent.futures import Future
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import AppKit

from src.jev_feishu.config import init_app_config, load_config
from src.jev_feishu.hud import HUDController
from src.jev_feishu.model_settings import ModelSettingsEditor
from tests.fixture_scenario import FixtureScenario
from tests.test_ui_state import ImmediateExecutor


class ModelSettingsUITests(unittest.TestCase):
    def setUp(self):
        AppKit.NSApplication.sharedApplication()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'app' / 'env'
        self.shared = Path(self.tmp.name) / 'shared'
        init_app_config(self.path)
        self.shared.write_text('TYPESAFE_BASE_URL=https://example.com/api\nTYPESAFE_API_KEY=fixture-shared-key\n')
        self.shared.chmod(0o600)
        self.scenario = FixtureScenario()
        self.runtime = self.scenario.make_runtime(ImmediateExecutor())
        self.addCleanup(self.scenario.close)
        self.addCleanup(self.runtime.close)
        self.hud = HUDController.alloc().init()
        self.hud.runtime = self.runtime
        self.hud.settings_panel = None
        self.hud._render = Mock()
        self.hud.hint = Mock()
        self.panel = Mock()
        self.panel.contentView.return_value = AppKit.NSView.alloc().initWithFrame_(((0,0),(720,780)))
        self.panel.isVisible.return_value = False
        self.factory = patch('src.jev_feishu.hud.ModelSettingsEditor',
                             side_effect=lambda: ModelSettingsEditor(self.path, self.shared))
        self.factory.start(); self.addCleanup(self.factory.stop)
        self.open()

    def open(self):
        with patch.object(AppKit, 'NSPanel') as panels, patch.object(AppKit, 'NSApplication'):
            panels.alloc.return_value.initWithContentRect_styleMask_backing_defer_.return_value = self.panel
            self.hud.showSettings_(None)

    def test_native_fields_are_editable_and_inherited_key_is_never_echoed(self):
        self.assertEqual(len(self.hud.model_fields), 6)
        for target in ('reply', 'jev'):
            self.assertTrue(self.hud.model_fields[(target, 'base')].isEditable())
            self.assertTrue(self.hud.model_fields[(target, 'model')].isEditable())
            self.assertIsInstance(self.hud.model_fields[(target, 'key')], AppKit.NSSecureTextField)
            self.assertEqual(self.hud.model_fields[(target, 'key')].stringValue(), '')
        self.assertEqual(self.hud.model_fields[('reply', 'model')].stringValue(), 'qwen3.5:4b')
        self.assertIn('共享 TypeSafe', self.hud.model_key_notes['jev'].stringValue())
        self.assertEqual(self.scenario.model_calls, [])

    def test_save_keeps_running_config_unchanged_and_clears_typed_keys(self):
        self.hud.model_fields[('reply','model')].setStringValue_('another-local-model')
        self.hud.model_fields[('jev','key')].setStringValue_('fixture-new-key')
        original_model = self.runtime.display().model
        original_url = self.runtime._generator._url
        self.hud.saveModels_(None)
        self.assertEqual(load_config(self.path, self.shared)['reply_model'], 'another-local-model')
        self.assertEqual(self.runtime.display().model, original_model)
        self.assertEqual(self.runtime._generator._url, original_url)
        self.assertEqual(self.hud.model_fields[('jev','key')].stringValue(), '')
        self.assertIn('重新打开', self.hud.model_settings_status.stringValue())
        self.assertEqual(self.scenario.model_calls, [])
        self.assertFalse(self.runtime._running)

    def test_model_list_uses_draft_and_preserves_manual_model(self):
        self.hud.model_fields[('reply','base')].setStringValue_('http://localhost:12000/v1')
        self.hud.model_fields[('reply','model')].setStringValue_('handwritten-model')
        self.hud._model_editor.list_models = Mock(return_value=('new-a','new-b'))
        before = self.path.read_bytes()
        sender = Mock(); sender.tag.return_value = 1
        self.hud.listModels_(sender)
        self.hud._poll_model_task()
        args = self.hud._model_editor.list_models.call_args.args
        self.assertEqual(args[0], 'reply')
        self.assertEqual(args[1]['reply_base'], 'http://localhost:12000/v1')
        field = self.hud.model_fields[('reply','model')]
        self.assertEqual(field.stringValue(), 'handwritten-model')
        self.assertEqual(list(field.objectValues()), ['new-a','new-b'])
        self.assertEqual(self.path.read_bytes(), before)
        self.hud.tick_(None)
        self.assertTrue(all(control.isEnabled() for control in self.hud.settings_controls))
        self.assertIsNone(self.hud._settings_future)

    def test_switching_protocol_does_not_reuse_another_service_key(self):
        self.hud.model_fields[('reply','key')].setStringValue_('fixture-local-key')
        self.hud.reply_protocol.selectItemWithTitle_('OpenAI 兼容')
        self.hud.replyProtocolChanged_(self.hud.reply_protocol)
        self.assertEqual(self.hud.model_fields[('reply','key')].stringValue(), '')
        self.assertEqual(self.hud.model_fields[('reply','model')].stringValue(), '')
        self.assertEqual(self.hud.model_fields[('reply','base')].stringValue(), 'https://api.openai.com/v1')
        self.hud.reply_protocol.selectItemWithTitle_('本机 Ollama')
        self.hud.replyProtocolChanged_(self.hud.reply_protocol)
        self.assertEqual(self.hud.model_fields[('reply','key')].stringValue(), 'fixture-local-key')

    def test_remote_save_discloses_destination_and_cancel_does_not_write(self):
        self.hud.reply_protocol.selectItemWithTitle_('OpenAI 兼容')
        self.hud.replyProtocolChanged_(self.hud.reply_protocol)
        self.hud.model_fields[('reply','model')].setStringValue_('fixture-model')
        self.hud.model_fields[('reply','key')].setStringValue_('fixture-new-key')
        before = self.path.read_bytes()
        with patch.object(AppKit, 'NSAlert') as alerts:
            alert = alerts.alloc.return_value.init.return_value
            alert.runModal.return_value = AppKit.NSAlertSecondButtonReturn
            self.hud.saveModels_(None)
        disclosure = alert.setInformativeText_.call_args.args[0]
        self.assertIn('https://api.openai.com/v1', disclosure)
        self.assertNotIn('fixture-new-key', disclosure)
        self.assertEqual(self.path.read_bytes(), before)

    def test_close_drops_pending_result_and_clears_secret_drafts(self):
        future = Future()
        self.hud._settings_future = (future, 'reply', 'list')
        self.hud.model_fields[('reply','key')].setStringValue_('fixture-new-key')
        self.hud._provider_forms = {'openai': ('fixture-new-key',)}
        notification = Mock(); notification.object.return_value = self.hud.settings_panel
        self.hud.windowWillClose_(notification)
        future.set_result(('obsolete-model',))
        self.hud._poll_model_task()
        self.assertEqual(self.hud.model_fields[('reply','key')].stringValue(), '')
        self.assertEqual(self.hud._provider_forms, {})
        self.assertIsNone(self.hud._settings_future)
        self.assertNotIn('obsolete-model', self.hud.model_fields[('reply','model')].objectValues())

    def test_concurrent_config_change_is_reported_without_overwrite(self):
        with self.path.open('a') as stream: stream.write('# external edit\n')
        original = self.path.read_bytes()
        self.hud.saveModels_(None)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn('其他操作修改', self.hud.model_settings_status.stringValue())

    def test_background_auth_check_does_not_disable_model_configuration(self):
        self.runtime._health_future = Future()
        self.hud.tick_(None)
        self.assertTrue(all(control.isEnabled() for control in self.hud.settings_controls))
        self.hud.model_fields[('reply', 'model')].setStringValue_('custom-local')
        self.hud.saveModels_(None)
        self.assertEqual(load_config(self.path, self.shared)['reply_model'], 'custom-local')
