from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from threading import Event
import unittest
from unittest.mock import Mock, patch

from src.jev_feishu.foreground import ChatEvidence, ChatObservation
from src.jev_feishu.runtime import AppRuntime
from src.jev_feishu.lark_reader import ReaderError
from src.jev_feishu.diagnostics import DependencyReport
from src.jev_feishu.http_client import ModelError
from src.jev_feishu.jev import JevJudge
from src.jev_feishu.types import ChatRef, TextMessage


REF = ChatRef("chat", "oc_fake")


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)
        return future

    def shutdown(self, **_kwargs):
        pass


class DeferredExecutor:
    def __init__(self):
        self.pending = []

    def submit(self, fn, *args):
        future = Future()
        self.pending.append((future, fn, args))
        return future

    def complete_next(self):
        future, fn, args = self.pending.pop(0)
        future.set_result(fn(*args))

    def shutdown(self, **_kwargs):
        pass


class FakeProbe:
    def __init__(self):
        self.current = ChatObservation(1, "com.electron.lark", "chat", 1, (), "虚构对象", True)

    def observe(self):
        return self.current


class RuntimeTests(unittest.TestCase):
    def test_mode_switch_discards_previous_reply_and_enables_viewport(self):
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertIsNotNone(self.runtime.display().result)
        self.runtime.set_follow_mode("visible")
        self.assertTrue(self.probe.follow_visible)
        self.assertIsNone(self.runtime.display().result)
        self.assertEqual(self.runtime.follow_mode, "visible")
        self.runtime.set_follow_mode("latest")
        self.assertFalse(self.probe.follow_visible)

    def setUp(self):
        self.probe = FakeProbe()
        self.reader = Mock()
        self.reader.list_recent.return_value = [
            TextMessage("om_fake", "ou_other", "虚构测试消息", "1000", None, False)]
        self.lookup = Mock()
        self.lookup.candidates.side_effect = lambda observation: replace(
            observation, candidates=(ChatEvidence(REF, True, True),))
        self.judge = Mock()
        self.judge.judge.return_value = None
        self.generator = Mock()
        self.generator.generate.return_value = ["虚构候选"] * 6
        self.runtime = AppRuntime(own_id="ou_self", probe=self.probe, lookup=self.lookup,
                                  reader=self.reader, judge=self.judge, generator=self.generator,
                                  executor=ImmediateExecutor(), config={
                                      "reply_model": "qwen3.5:4b", "typesafe_base": "https://openrouter.ai/api",
                                      "typesafe_key": "", "typesafe_model": "~typesafe/jev-latest",
                                      "ollama_base": "http://127.0.0.1:11434/v1",
                                  }, save_jev_setting=Mock(), save_tones=Mock())

    def test_default_pause_and_verified_current_chat(self):
        self.assertEqual(self.runtime.display().status, "paused")
        self.runtime.pulse()
        self.reader.list_recent.assert_not_called()
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        state = self.runtime.display()
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.chat_title, "虚构对象")
        self.assertEqual(len(state.result.replies), 6)
        self.assertEqual(state.result.source_text, "虚构测试消息")
        self.assertNotIn("虚构测试消息", repr(state.result))
        self.assertTrue(state.cloud_enabled)

    def test_switch_clears_and_does_not_read_unknown_chat(self):
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.probe.current = ChatObservation(2, "com.electron.lark", "unknown", 1)
        self.runtime.pulse()
        state = self.runtime.display()
        self.assertIsNone(state.chat_title)
        self.assertIsNone(state.result)
        self.assertEqual(state.status, "unidentified")

    def test_missing_accessibility_does_not_read(self):
        self.probe.current = ChatObservation(2, "com.electron.lark", "permission_required", 0)
        self.runtime.start()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().status, "accessibility_required")
        self.reader.list_recent.assert_not_called()

    @patch("src.jev_feishu.runtime.monotonic")
    def test_identity_lookup_recovers_without_leaving_current_chat(self, clock):
        clock.return_value = 100
        observation = self.probe.current
        self.lookup.candidates.side_effect = [observation, replace(
            observation, candidates=(ChatEvidence(REF, True, True),))]
        self.runtime.start()
        self.runtime.pulse()
        self.assertIsNone(self.runtime.current_ref)
        self.reader.list_recent.assert_not_called()

        clock.return_value = 102.9
        self.runtime.pulse()
        self.assertEqual(self.lookup.candidates.call_count, 1)
        clock.return_value = 103
        self.runtime.pulse()
        self.runtime.pulse()

        self.assertEqual(self.lookup.candidates.call_count, 2)
        self.assertEqual(self.runtime.current_ref, REF)
        self.assertEqual(len(self.runtime.display().result.replies), 6)
        self.assertTrue(self.runtime.display().cloud_enabled)

    @patch("src.jev_feishu.runtime.monotonic")
    def test_unresolved_identity_retries_with_backoff_without_reading(self, clock):
        self.lookup.candidates.side_effect = lambda observation: observation
        clock.return_value = 100
        self.runtime.start()
        self.runtime.pulse()
        for count, due in enumerate((103, 109, 121, 145, 193, 253, 313), start=1):
            clock.return_value = due - 0.1
            self.runtime.pulse()
            self.assertEqual(self.lookup.candidates.call_count, count)
            clock.return_value = due
            self.runtime.pulse()
            self.assertEqual(self.lookup.candidates.call_count, count + 1)
        self.assertIsNone(self.runtime.current_ref)
        self.reader.list_recent.assert_not_called()
        self.generator.generate.assert_not_called()
        self.judge.judge.assert_not_called()

    @patch("src.jev_feishu.runtime.monotonic")
    def test_new_chat_is_resolved_immediately_during_identity_backoff(self, clock):
        clock.return_value = 100
        self.lookup.candidates.side_effect = lambda observation: observation
        self.runtime.start()
        self.runtime.pulse()
        self.reader.list_recent.assert_not_called()

        other = ChatRef("chat", "oc_other")
        self.probe.current = replace(self.probe.current, epoch=2, title="另一虚构会话")
        self.lookup.candidates.side_effect = lambda observation: replace(
            observation, candidates=(ChatEvidence(other, True, True),))
        clock.return_value = 101
        self.runtime.pulse()
        self.runtime.pulse()

        self.assertEqual(self.lookup.candidates.call_count, 2)
        self.assertEqual(self.runtime.current_ref, other)
        self.reader.list_recent.assert_called_once_with(other)

    def test_overlay_and_pause(self):
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.runtime.set_overlay_focused(True)
        self.assertEqual(len(self.runtime.display().result.replies), 6)
        self.runtime.pulse()
        self.runtime.pause()
        self.assertIsNone(self.runtime.display().result)
        self.assertEqual(self.runtime.display().status, "paused")

    def test_invalidation_is_reflected_in_visible_candidates(self):
        for messages, status in (([], "no_text"),
                ([TextMessage("om_fake", "", "", "1000", None, True)], "message_deleted"),
                ([TextMessage("om_self", "ou_self", "虚构本人回复", "2000", None, False)], "own_message")):
            with self.subTest(status=status):
                self.setUp()
                self.runtime.start()
                self.runtime.pulse()
                self.runtime.pulse()
                self.assertEqual(len(self.runtime.display().result.replies), 6)
                self.reader.list_recent.return_value = messages
                self.runtime._session._next_poll = 0
                self.runtime._next_read_at = 0
                self.runtime.pulse()
                self.runtime.pulse()
                self.assertIsNone(self.runtime.display().result)
                self.assertEqual(self.runtime.display().status, status)

    def test_read_failure_clears_visible_candidate_and_reports_error(self):
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.reader.list_recent.side_effect = ReaderError("cli_error")
        self.runtime._session._next_poll = 0
        self.runtime._next_read_at = 0
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertIsNone(self.runtime.display().result)
        self.assertEqual(self.runtime.display().status, "read_error")

    def test_losing_overlay_focus_does_not_unpause_status(self):
        self.runtime.set_overlay_focused(True)
        self.runtime.set_overlay_focused(False)
        self.assertEqual(self.runtime.display().status, "paused")

    def test_global_switch_applies_without_a_current_chat_and_survives_switch(self):
        self.assertTrue(self.runtime.display().cloud_enabled)
        self.assertTrue(self.runtime.set_jev_enabled(False))
        self.assertFalse(self.runtime.display().cloud_enabled)
        self.runtime.start()
        self.runtime.pulse()
        self.probe.current = ChatObservation(2, None, "unknown", 0)
        self.runtime.pulse()
        self.assertFalse(self.runtime.display().cloud_enabled)
        self.runtime._save_jev_setting.assert_called_once_with(False)

    def test_failed_global_setting_save_keeps_previous_value(self):
        self.runtime._save_jev_setting.side_effect = OSError("private path")
        self.assertFalse(self.runtime.set_jev_enabled(False))
        self.assertTrue(self.runtime.jev_enabled)
        self.assertIn("保存失败", self.runtime.settings_text())
        self.assertNotIn("private path", self.runtime.settings_text())

    def test_manual_mode_is_explicit_and_exit_rechecks_auto(self):
        self.runtime.enter_manual(REF)
        self.assertEqual(self.runtime.display().status, "manual")
        self.assertEqual(self.runtime.display().chat_title, REF.value)
        self.runtime.pulse()
        self.runtime.exit_manual()
        self.assertIsNone(self.runtime.display().chat_title)
        self.assertEqual(self.runtime.display().status, "looking_for_chat")

    def test_manual_mode_after_auto_does_not_require_foreground_observation(self):
        self.runtime.start()
        self.runtime.pulse()
        self.reader.list_recent.reset_mock()
        self.probe.current = ChatObservation(2, None, "unknown", 0)

        self.runtime.enter_manual(REF)
        self.runtime.pulse()
        self.runtime.pulse()

        self.reader.list_recent.assert_called_once_with(REF)
        self.assertEqual(self.runtime.display().status, "manual")

    def test_foreground_probe_runs_off_ui_pulse_and_pause_ignores_late_result(self):
        executor = DeferredExecutor()
        runtime = AppRuntime(own_id="ou_self", probe=self.probe, lookup=self.lookup,
                             reader=self.reader, judge=self.judge, generator=self.generator,
                             executor=executor, config=self.runtime._config)
        self.probe.observe = Mock(return_value=self.probe.current)
        runtime.start()
        runtime.pulse()
        self.probe.observe.assert_not_called()
        self.assertEqual(runtime.display().status, "looking_for_chat")
        runtime.pause()
        executor.complete_next()
        runtime.pulse()
        self.reader.list_recent.assert_not_called()
        self.assertEqual(runtime.display().status, "paused")

    def test_startup_auth_failure_keeps_runtime_available_and_stops_reading(self):
        executor = DeferredExecutor()
        diagnostics = Mock()
        diagnostics.check.return_value = DependencyReport("ready", "unavailable", "ready", "configured")
        runtime = AppRuntime(probe=self.probe, lookup=self.lookup, reader=self.reader,
                             executor=executor, config=self.runtime._config, diagnostics=diagnostics)
        self.assertEqual(runtime.display().status, "checking_dependencies")
        runtime.start()
        self.assertFalse(runtime._running)
        executor.complete_next()
        runtime.pulse()
        self.assertEqual(runtime.display().status, "lark_auth_unavailable")
        self.assertIsNone(runtime.display().chat_title)
        self.reader.list_recent.assert_not_called()
        runtime.pause()
        self.assertEqual(runtime.display().status, "lark_auth_unavailable")
        self.assertTrue(runtime.can_recheck)

        diagnostics.check.return_value = DependencyReport("ready", "ready", "ready", "configured",
                                                         own_id="ou_self")
        runtime.refresh_dependencies()
        runtime.pause()
        self.assertEqual(runtime.display().status, "checking_dependencies")
        self.assertFalse(runtime.can_recheck)
        executor.complete_next()
        runtime.pulse()
        self.assertEqual(runtime.display().status, "paused")
        self.assertFalse(runtime._running)
        self.reader.list_recent.assert_not_called()
        runtime.start()
        self.assertTrue(runtime._running)

    def test_failed_checks_remain_visible_when_paused_and_can_be_retried(self):
        for cli, auth, status in (("ready", "connection_error", "lark_check_failed"),
                                  ("ready", "verification_failed", "lark_check_failed"),
                                  ("missing", "unavailable", "lark_cli_missing")):
            with self.subTest(auth=auth, cli=cli):
                diagnostics = Mock()
                diagnostics.check.return_value = DependencyReport(cli, auth, "ready", "configured")
                runtime = AppRuntime(reader=self.reader, executor=ImmediateExecutor(),
                                     config=self.runtime._config, diagnostics=diagnostics)
                self.addCleanup(runtime.close)
                runtime.pulse()
                self.assertEqual(runtime.display().status, status)
                runtime.pause()
                self.assertEqual(runtime.display().status, status)
                self.assertTrue(runtime.can_recheck)
                self.assertFalse(runtime.can_start)
                runtime.start()
                self.assertFalse(runtime._running)
                self.reader.list_recent.assert_not_called()

    def test_unverified_report_with_cached_identity_cannot_enable_start(self):
        diagnostics = Mock()
        diagnostics.check.return_value = DependencyReport("ready", "verification_failed", "ready", "configured",
                                                         own_id="ou_fixture")
        runtime = AppRuntime(reader=self.reader, executor=ImmediateExecutor(),
                             config=self.runtime._config, diagnostics=diagnostics)
        self.addCleanup(runtime.close)
        runtime.pulse()
        self.assertFalse(runtime.can_start)
        self.assertEqual(runtime.display().status, "lark_check_failed")
        self.reader.list_recent.assert_not_called()

    def test_new_chat_clears_old_reply_before_identity_lookup_finishes(self):
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertIsNotNone(self.runtime.display().result)
        started, release = Event(), Event()
        executor = ThreadPoolExecutor(max_workers=2)
        self.runtime._pool = executor
        self.probe.current = replace(self.probe.current, epoch=2, title="另一虚构会话")
        def slow_lookup(observation):
            started.set()
            release.wait(2)
            return replace(observation, candidates=(ChatEvidence(REF, True, True),))
        self.lookup.candidates.side_effect = slow_lookup
        try:
            self.runtime.pulse()
            self.assertTrue(started.wait(1))
            self.runtime.pulse()
            self.assertIsNone(self.runtime.display().result)
            self.assertIsNone(self.runtime.display().chat_title)
            self.assertEqual(self.runtime.display().status, "looking_for_chat")
        finally:
            release.set()
            self.runtime.close()
            executor.shutdown(wait=True)

    def test_model_change_replaces_current_reply_without_new_incoming_message(self):
        self.generator.generate.side_effect = lambda item, model, **kwargs: [model] * 6
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().result.replies[0], "qwen3.5:4b")
        self.runtime.set_model("qwen3.5:9b")
        self.assertIsNone(self.runtime.display().result)
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().result.replies[0], "qwen3.5:9b")

    def test_tone_change_regenerates_with_selected_snapshot(self):
        self.generator.generate.side_effect = lambda item, model, **kwargs: list(kwargs["tones"]) * 2
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().result.replies[1], "高情商协作")
        self.assertTrue(self.runtime.set_tone(1, "高情商拒绝加班"))
        self.assertIsNone(self.runtime.display().result)
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().tones[1], "高情商拒绝加班")
        self.assertEqual(self.runtime.display().result.replies[1], "高情商拒绝加班")
        self.runtime._save_tones.assert_called_once_with(
            ("专业直接", "高情商拒绝加班", "轻松同事"))

    def test_invalid_or_failed_tone_change_preserves_state(self):
        before = self.runtime.display().tones
        self.assertFalse(self.runtime.set_tone(3, "高情商拒绝加班"))
        self.assertFalse(self.runtime.set_tone(1, "unknown"))
        self.runtime._save_tones.side_effect = OSError("private path")
        self.assertFalse(self.runtime.set_tone(1, "高情商拒绝加班"))
        self.assertEqual(self.runtime.display().tones, before)

    def test_focus_return_keeps_tone_choice_until_verified_read(self):
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.runtime.set_overlay_focused(True)
        self.assertTrue(self.runtime.set_tone(1, "高情商拒绝加班"))
        self.runtime.set_overlay_focused(False)
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().tones[1], "高情商拒绝加班")
        self.assertEqual(self.generator.generate.call_args.kwargs["tones"],
                         ("专业直接", "高情商拒绝加班", "轻松同事"))

    def test_cloud_change_rejudges_current_message_and_discards_old_verdict(self):
        def transport(url, headers, payload, timeout):
            return {"answers": {"intent": {"choice": "闲聊", "confidence": 0.8}, "risk": {"score": 0}}}
        self.runtime._judge = JevJudge("https://openrouter.ai/api", "fake-key", "fake-model",
                                      self.runtime._gate, transport)
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().result.verdict.intent, "闲聊")
        self.runtime.set_jev_enabled(False)
        self.assertIsNone(self.runtime.display().result)
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertIsNone(self.runtime.display().result.verdict)
        self.runtime.set_jev_enabled(True)
        self.assertIsNone(self.runtime.display().result)
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().result.verdict.intent, "闲聊")

    def test_explicit_retry_recovers_from_model_error_on_same_message(self):
        self.generator.generate.side_effect = ModelError("connection_error")
        self.runtime.start()
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().status, "connection_error")
        self.generator.generate.side_effect = None
        self.assertTrue(self.runtime.retry_current())
        self.runtime.pulse()
        self.runtime.pulse()
        self.assertEqual(self.runtime.display().status, "ready")
        self.assertEqual(len(self.runtime.display().result.replies), 6)

    def test_closed_runtime_cannot_resume_or_launch_diagnostics(self):
        self.runtime.close()
        self.assertFalse(self.runtime.can_start)
        self.assertFalse(self.runtime.can_recheck)
        self.runtime.start()
        self.runtime.refresh_dependencies()
        self.runtime.test_connection("jev")
        self.runtime.pulse()
        self.assertFalse(self.runtime._running)
        self.assertFalse(self.runtime.diagnostics_busy)
        self.reader.list_recent.assert_not_called()

    def test_late_startup_check_cannot_reopen_closed_runtime(self):
        executor = DeferredExecutor()
        diagnostics = Mock()
        diagnostics.check.return_value = DependencyReport("ready", "ready", "ready", "configured",
                                                         own_id="ou_self")
        runtime = AppRuntime(executor=executor, config=self.runtime._config, diagnostics=diagnostics)
        runtime.close()
        executor.complete_next()
        runtime.pulse()
        self.assertFalse(runtime.can_start)
        self.assertEqual(runtime.display().status, "paused")
