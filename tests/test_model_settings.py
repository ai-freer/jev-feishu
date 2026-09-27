import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.jev_feishu.config import init_app_config, load_config, read_env, save_jev_enabled
from src.jev_feishu.diagnostics import Diagnostics
from src.jev_feishu.http_client import ModelError
from src.jev_feishu.jev import endpoint
from src.jev_feishu.model_services import model_list, reply_options, service_endpoint, validate_base
from src.jev_feishu.model_settings import ModelSettingsEditor, settings_error
from src.jev_feishu.replies import ReplyGenerator
from tests.test_replies import answer, item
from tests.test_diagnostics import auth_ok


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name) / 'app' / 'env'
        self.shared = Path(self.tmp.name) / 'shared'
        init_app_config(self.app)
        self.shared.write_text("TYPESAFE_BASE_URL=https://example.com/api\nTYPESAFE_API_KEY=fixture-shared-key\n"
                               "TYPESAFE_DEFAULT_MODEL=fixture-jev\n")
        self.shared.chmod(0o600)
        self.editor = ModelSettingsEditor(self.app, self.shared)

    def test_defaults_remain_local_and_public_form_does_not_include_keys(self):
        values = self.editor.public_values()
        self.assertEqual(values['reply_provider'], 'ollama')
        self.assertEqual(values['reply_model'], 'qwen3.5:4b')
        self.assertEqual(values['typesafe_model'], 'fixture-jev')
        self.assertNotIn('fixture-shared-key', repr(values))
        self.assertNotIn('fixture-shared-key', repr(self.editor))
        self.assertEqual(self.editor.key_note('jev'), '共享 TypeSafe')

    def test_saves_arbitrary_models_and_addresses_without_copying_shared_key(self):
        shared = self.shared.read_bytes()
        with self.app.open('a') as stream:
            stream.write("# preserve\nCUSTOM='leave me'\n")
        editor = ModelSettingsEditor(self.app, self.shared)
        values = editor.public_values()
        values.update(reply_model='another-local-model:latest', reply_base='http://localhost:12000/v1',
                      typesafe_model='~typesafe/alternate')
        editor.save(values)
        loaded = load_config(self.app, self.shared)
        self.assertEqual(loaded['reply_model'], 'another-local-model:latest')
        self.assertEqual(loaded['reply_base'], 'http://localhost:12000/v1')
        self.assertEqual(loaded['typesafe_model'], '~typesafe/alternate')
        self.assertEqual(loaded['typesafe_key'], 'fixture-shared-key')
        self.assertNotIn('fixture-shared-key', self.app.read_text())
        self.assertNotIn('JEV_FEISHU_TYPESAFE_API_KEY', self.app.read_text())
        self.assertIn("CUSTOM='leave me'", self.app.read_text())
        self.assertIn('# preserve', self.app.read_text())
        self.assertEqual(self.app.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.shared.read_bytes(), shared)

    def test_endpoint_change_requires_explicit_key_handling(self):
        before = self.app.read_bytes()
        values = self.editor.public_values()
        values['typesafe_base'] = 'https://different.example/v1'
        for method in (self.editor.preview, self.editor.save):
            with self.assertRaisesRegex(ValueError, 'new_service_key_required'):
                method(values)
        self.assertEqual(self.app.read_bytes(), before)
        self.editor.save(values, keys={'jev': 'fixture-new-key'})
        config = load_config(self.app, self.shared)
        self.assertEqual(config['typesafe_key'], 'fixture-new-key')
        self.assertEqual(config['typesafe_key_source'], '本应用')

    def test_clear_masks_shared_key_and_moved_address_never_inherits_it(self):
        values = self.editor.public_values()
        self.editor.save(values, clear=('jev',))
        self.assertEqual(load_config(self.app, self.shared)['typesafe_key'], '')
        self.app.write_text('JEV_FEISHU_TYPESAFE_BASE_URL=https://different.example/v1\n')
        self.assertEqual(load_config(self.app, self.shared)['typesafe_key'], '')

    def test_keeps_existing_app_keys_if_fields_left_blank(self):
        values = self.editor.public_values()
        values.update(reply_provider='openai', reply_base='https://example.com/v4', reply_model='fixture-reply')
        self.editor.save(values, keys={'reply': 'fixture-reply-key', 'jev': 'fixture-app-key'})
        self.editor.save(self.editor.public_values(), keys={'reply': '', 'jev': ''})
        config = load_config(self.app, self.shared)
        self.assertEqual(config['reply_key'], 'fixture-reply-key')
        self.assertEqual(config['typesafe_key'], 'fixture-app-key')
        self.assertEqual(config['reply_provider'], 'openai')

    def test_invalid_values_conflicts_and_atomic_failure_preserve_document(self):
        for field, value in (('reply_base', 'http://remote.example'), ('reply_model', ''),
                             ('reply_provider', 'unknown')):
            before = self.app.read_bytes()
            values = self.editor.public_values(); values[field] = value
            with self.assertRaises(ValueError): self.editor.save(values)
            self.assertEqual(self.app.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.editor.save(self.editor.public_values(), keys={'reply': 'injected\nVALUE=bad'})
        before = self.app.read_bytes()
        with patch('src.jev_feishu.config.os.replace', side_effect=OSError('sensitive')):
            values = self.editor.public_values(); values['reply_model'] = 'changed-model'
            with self.assertRaises(OSError): self.editor.save(values)
        self.assertEqual(self.app.read_bytes(), before)
        self.assertEqual(list(self.app.parent.glob('.jev-env-*')), [])
        with self.app.open('a') as stream: stream.write('# concurrent edit\n')
        changed = self.app.read_bytes()
        with self.assertRaisesRegex(ValueError, 'config_changed'): self.editor.save(self.editor.public_values())
        self.assertEqual(self.app.read_bytes(), changed)
        self.assertNotIn('sensitive', settings_error(OSError('sensitive')))

    def test_unchanged_save_does_not_pin_inherited_values_and_edits_keep_inline_comments(self):
        original = self.app.read_bytes()
        self.editor.save(self.editor.public_values())
        self.assertEqual(self.app.read_bytes(), original)
        self.app.write_text('JEV_FEISHU_REPLY_MODEL=qwen3.5:4b # local default\n')
        editor = ModelSettingsEditor(self.app, self.shared)
        values = editor.public_values(); values['reply_model'] = 'new-model'
        editor.save(values)
        self.assertIn('JEV_FEISHU_REPLY_MODEL=new-model # local default', self.app.read_text())
        self.assertNotIn('TYPESAFE_BASE_URL', self.app.read_text())

    def test_draft_test_and_list_do_not_require_valid_other_form_or_save(self):
        values = self.editor.public_values(); values['reply_model'] = ''
        before = self.app.read_bytes()
        with patch('src.jev_feishu.model_settings.model_list', return_value=('new-jev',)) as listing:
            self.assertEqual(self.editor.list_models('jev', values), ('new-jev',))
        listing.assert_called_once_with('jev', 'https://example.com/api', 'fixture-shared-key')
        with patch('src.jev_feishu.model_settings.Diagnostics') as diagnostics:
            self.editor.test('jev', values)
        self.assertEqual(self.app.read_bytes(), before)
        self.assertEqual(diagnostics.call_args.args[0]['typesafe_model'], 'fixture-jev')

    def test_global_toggle_rebases_only_the_expected_single_setting(self):
        save_jev_enabled(False, self.app)
        self.editor.after_global_toggle()
        self.editor.save(self.editor.public_values())
        self.assertFalse(load_config(self.app, self.shared)['jev_enabled'])
        with self.app.open('a') as stream: stream.write('CUSTOM=changed\n')
        with self.assertRaisesRegex(ValueError, 'config_changed'): self.editor.after_global_toggle()

    def test_changing_protocol_keeps_the_explicit_local_address_on_reload(self):
        values = self.editor.public_values()
        values['reply_provider'] = 'openai'
        self.editor.save(values)
        config = load_config(self.app, self.shared)
        self.assertEqual(config['reply_provider'], 'openai')
        self.assertEqual(config['reply_base'], 'http://127.0.0.1:11434/v1')


class ModelServiceTests(unittest.TestCase):
    def test_arbitrary_local_model_is_passed_to_the_configured_endpoint(self):
        post = Mock(return_value=answer())
        generator = ReplyGenerator('http://localhost:12000', post)
        self.assertEqual(len(generator.generate(item(), 'custom-reply-model:latest')), 6)
        for call in post.call_args_list:
            self.assertEqual(call.args[0], 'http://localhost:12000/v1/chat/completions')
            self.assertEqual(call.args[2]['model'], 'custom-reply-model:latest')

    def test_endpoints_support_versions_and_complete_urls(self):
        for base, expected in (('https://example.com', 'https://example.com/v1/chat/completions'),
                               ('https://example.com/v4/', 'https://example.com/v4/chat/completions'),
                               ('https://example.com/api/v1/chat/completions', 'https://example.com/api/v1/chat/completions')):
            self.assertEqual(service_endpoint('openai', base), expected)
        self.assertEqual(service_endpoint('anthropic', 'https://example.com/api'), 'https://example.com/api/v1/messages')
        self.assertEqual(endpoint('https://example.com/v2'), 'https://example.com/v2/systemone')
        self.assertEqual(endpoint('https://example.com/v1/evaluate'), 'https://example.com/v1/evaluate')
        for value in ('http://remote.example', 'https://a:secret@example.com', 'https://example.com?k=secret',
                      'https://example.com/#fragment', 'https://example.com:bad', 'https://example.com/\nroute',
                      'https://example.com?', 'https://example.com#'):
            with self.assertRaises(ValueError): validate_base(value)
        for value in ('http://127.0.0.1:11434', 'http://localhost:12000/v1', 'http://[::1]:11434/v1'):
            self.assertEqual(validate_base(value, local_only=True), value)
        with self.assertRaises(ValueError): service_endpoint('ollama', 'https://remote.example/v1')

    def test_openai_request_uses_selected_model_and_key_without_ollama_parameters(self):
        post = Mock(return_value=answer())
        result = ReplyGenerator('https://example.com/v4', post, provider='openai', key='fixture-key').generate(item(), 'fixture/model')
        self.assertEqual(len(result), 6)
        url, headers, payload, _ = post.call_args.args
        self.assertEqual(url, 'https://example.com/v4/chat/completions')
        self.assertEqual(headers['authorization'], 'Bearer fixture-key')
        self.assertEqual(payload['model'], 'fixture/model')
        self.assertNotIn('reasoning_effort', payload)
        self.assertEqual([m['role'] for m in payload['messages']], ['system', 'user'])

    def test_anthropic_request_and_text_block_response(self):
        post = Mock(return_value={'content': [{'type': 'text', 'text': '虚构回复一'}, {'type': 'text', 'text': '虚构回复二'}]})
        result = ReplyGenerator('https://example.com', post, provider='anthropic', key='fixture-key').generate(item(), 'fixture-model')
        self.assertEqual(result, ['虚构回复一', '虚构回复二'] * 3)
        url, headers, payload, _ = post.call_args.args
        self.assertEqual(url, 'https://example.com/v1/messages')
        self.assertEqual(headers['x-api-key'], 'fixture-key')
        self.assertEqual(headers['anthropic-version'], '2023-06-01')
        self.assertNotIn('authorization', headers)
        self.assertIn('system', payload)
        self.assertEqual([m['role'] for m in payload['messages']], ['user'])

    def test_remote_missing_key_never_calls_a_service_or_falls_back(self):
        post = Mock()
        generator = ReplyGenerator('https://example.com', post, provider='openai')
        with self.assertRaisesRegex(ModelError, 'not_configured'): generator.generate(item(), 'fixture-model')
        post.assert_not_called()

    def test_model_lists_cover_native_jev_gateway_openai_and_anthropic_pages(self):
        get = Mock(return_value={'models': [{'name': 'jev-custom'}]})
        self.assertEqual(model_list('jev', 'https://example.com', 'fixture-key', get=get), ('jev-custom',))
        get = Mock(return_value={'data': [{'id': 'typesafe/jev-1'}, {'id': 'another/model'}]})
        self.assertEqual(model_list('jev', 'https://openrouter.ai/api', 'fixture-key', get=get), ('typesafe/jev-1',))
        get = Mock(side_effect=[{'data': [{'id': 'a'}], 'has_more': True, 'last_id': 'a'},
                                {'data': [{'id': 'b'}], 'has_more': False}])
        self.assertEqual(model_list('anthropic', 'https://example.com', 'fixture-key', get=get), ('a', 'b'))
        self.assertTrue(get.call_args.args[0].endswith('/v1/models?after_id=a'))
        self.assertEqual(get.call_args.kwargs['headers']['x-api-key'], 'fixture-key')
        with self.assertRaisesRegex(ModelError, 'models_unavailable'):
            model_list('jev', 'https://example.com/v1/evaluate', 'fixture-key', get=get)
        for data in ({'data': 'bad'}, {'data': [{}]}, {'data': [], 'has_more': True}):
            with self.assertRaises(ModelError):
                model_list('openai', 'https://example.com', '', get=Mock(return_value=data))

    def test_startup_discovers_all_local_models_but_no_remote_models_or_prompts(self):
        cfg = {'reply_model': 'custom-model', 'ollama_base': 'http://127.0.0.1:11434/v1', 'typesafe_key': ''}
        get = Mock(return_value={'data': [{'id': 'custom-model'}, {'id': 'third-model'}]})
        post = Mock()
        report = Diagnostics(cfg, cli_lookup=lambda: 'fixture-cli', runner=auth_ok, get=get, post=post).check()
        self.assertEqual(report.available_models, ('custom-model', 'third-model'))
        self.assertEqual(report.ollama, 'ready')
        cfg.update(reply_provider='openai', reply_base='https://example.com', reply_key='fixture-key')
        get.reset_mock()
        report = Diagnostics(cfg, cli_lookup=lambda: 'fixture-cli', runner=auth_ok, get=get, post=post).check()
        self.assertEqual(report.ollama, 'configured')
        get.assert_not_called(); post.assert_not_called()
