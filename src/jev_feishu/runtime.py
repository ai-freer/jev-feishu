"""Connect foreground observation, identity lookup, read and model workers."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from time import monotonic

from .chat_resolver import ChatResolver, LarkIdentityLookup
from .config import load_config, save_jev_enabled
from .diagnostics import Diagnostics, DependencyReport
from .foreground import ForegroundProbe
from .http_client import ModelError
from .jev import JevJudge, Verdict
from .lark_reader import LarkReader
from .privacy import PrivacyGate
from .replies import ReplyGenerator
from .session import AnalysisInput, SessionController
from .types import ChatRef


@dataclass(frozen=True, repr=False)
class ResultBundle:
    replies: tuple[str, ...]
    verdict: Verdict | None
    error: str | None = None


@dataclass(frozen=True, repr=False)
class DisplayState:
    status: str
    chat_title: str | None
    model: str
    cloud_enabled: bool
    result: ResultBundle | None


class AppRuntime:
    def __init__(self, *, own_id=None, probe=None, lookup=None, reader=None,
                 gate=None, judge=None, generator=None, executor=None, config=None, diagnostics=None,
                 save_jev_setting=save_jev_enabled):
        self._config = config or load_config()
        self._probe = probe or ForegroundProbe()
        self._lookup = lookup or LarkIdentityLookup()
        self._resolver = ChatResolver()
        self._gate = gate if gate is not None else PrivacyGate(self._config.get("jev_enabled", True))
        self._save_jev_setting = save_jev_setting
        self._reader = reader or LarkReader()
        self._session = SessionController(self._reader, own_id) if own_id else None
        self._judge = judge or JevJudge(self._config["typesafe_base"], self._config["typesafe_key"],
                                        self._config["typesafe_model"], self._gate)
        self._generator = generator or ReplyGenerator(self._config["ollama_base"])
        self._pool = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="jev-feishu")
        self._model = self._config["reply_model"]
        self._running = False
        self._manual = False
        self._overlay_focused = False
        self._observed_epoch = None
        self._resolved_ref: ChatRef | None = None
        self._title: str | None = None
        self._detect_future = None
        self._detect_token = None
        self._next_lookup_at = 0.0
        self._lookup_delay = 3.0
        self._observations = SimpleQueue()
        self._read_future = None
        self._next_read_at = 0.0
        self._model_futures = []
        self._status = "paused"
        self._result: ResultBundle | None = None
        self._diagnostics = diagnostics or Diagnostics(self._config)
        self._health = DependencyReport("unchecked", "unchecked", "unchecked", "unchecked")
        self._health_future = None
        self._test_future = None
        self._test_status = "连接测试只使用虚构问候；不会开启任何真实会话的 Jev。"
        self._closed = False
        if own_id is None:
            self.refresh_dependencies()

    @property
    def can_start(self):
        return not self._closed and self._session is not None and self._health_future is None

    @property
    def diagnostics_busy(self):
        return self._health_future is not None or self._test_future is not None

    @property
    def current_ref(self) -> ChatRef | None:
        return self._session.current_ref if self._session is not None else None

    def settings_text(self):
        return (self._diagnostics.configuration_text(self._model) + "\n\n"
                + self._health.summary() + "\n可用回复模型："
                + ("、".join(self._health.available_models) or "尚未检测到")
                + "\n\n" + self._test_status)

    @property
    def jev_enabled(self):
        return self._gate.allows_cloud()

    def refresh_dependencies(self):
        if self._closed or self._health_future is not None:
            return
        self.pause()
        self._status = "checking_dependencies"
        self._health_future = self._pool.submit(self._diagnostics.check)

    def test_connection(self, target):
        if self._closed or self.diagnostics_busy:
            return
        self._test_status = "正在使用虚构问候测试连接…"
        self._test_future = self._pool.submit(self._diagnostics.test_connection, target, self._model)

    def _poll_diagnostics(self):
        if self._health_future is not None and self._health_future.done():
            future, self._health_future = self._health_future, None
            try:
                self._health = future.result()
            except Exception:
                self._health = DependencyReport("unchecked", "unavailable", "unchecked", "unchecked")
            self._session = (SessionController(self._reader, self._health.own_id)
                             if self._health.own_id else None)
            self._status = "paused" if self._session else "lark_auth_unavailable"
        if self._test_future is not None and self._test_future.done():
            future, self._test_future = self._test_future, None
            try:
                self._test_status = future.result().summary()
            except Exception:
                self._test_status = "连接测试失败；请检查配置和服务状态。"

    def start(self):
        if not self.can_start:
            return
        self._session.resume()
        self._manual = False
        self._running = True
        self._observed_epoch = None
        self._detect_future = None
        self._detect_token = None
        self._next_lookup_at = 0.0
        self._lookup_delay = 3.0
        self._read_future = None
        self._next_read_at = 0.0
        self._status = "looking_for_chat"

    def pause(self):
        self._running = False
        self._manual = False
        if self._session is not None:
            self._session.pause()
        self._resolved_ref = None
        self._title = None
        self._result = None
        self._status = "paused"
        self._detect_future = None
        self._detect_token = None
        self._read_future = None
        self._model_futures = []

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.pause()
        self._health_future = None
        self._test_future = None
        self._pool.shutdown(wait=False, cancel_futures=True)

    def set_overlay_focused(self, focused: bool):
        self._overlay_focused = focused
        if self._session is not None:
            self._session.set_overlay_focused(focused)
        if not focused and not self._manual:
            self._observed_epoch = None
            self._resolved_ref = None
            self._title = None
            self._result = None
            if self._running:
                self._status = "looking_for_chat"

    def set_model(self, model: str):
        if model not in ("qwen3.5:4b", "qwen3.5:9b"):
            raise ValueError("unsupported_reply_model")
        if model != self._model:
            self._model = model
            self.retry_current()

    def retry_current(self) -> bool:
        if self._closed or self._session is None or not self._session.refresh_current():
            return False
        self._read_future = None
        self._model_futures = []
        self._next_read_at = 0.0
        self._result = None
        self._status = "refreshing"
        return True

    def enter_manual(self, ref: ChatRef) -> None:
        if not self.can_start:
            return
        self._session.enter_manual(ref)
        self._manual = True
        self._running = True
        self._observed_epoch = None
        self._resolved_ref = ref
        self._title = ref.value
        self._result = None
        self._status = "manual"
        self._detect_future = None
        self._detect_token = None
        self._read_future = None
        self._next_read_at = 0.0

    def exit_manual(self) -> None:
        self._session.pause()
        self._session.resume()
        self._manual = False
        self._resolved_ref = None
        self._title = None
        self._result = None
        self._observed_epoch = None
        self._status = "looking_for_chat"
        self._read_future = None

    def set_jev_enabled(self, enabled: bool) -> bool:
        if type(enabled) is not bool or self._closed:
            return False
        if self.jev_enabled == enabled:
            return True
        try:
            self._save_jev_setting(enabled)
        except (OSError, ValueError):
            self._test_status = "Jev 设置保存失败；全局开关未改变。"
            return False
        self._gate.set_cloud(enabled)
        self._config["jev_enabled"] = enabled
        self._test_status = "Jev 全局设置已保存。"
        self.retry_current()
        return True

    def display(self) -> DisplayState:
        ref = self._session.current_ref if self._session is not None else None
        return DisplayState(self._status, self._title if ref else None, self._model,
                            self.jev_enabled, self._session.candidate if ref else None)

    def pulse(self):
        if self._closed:
            return
        self._poll_diagnostics()
        if not self._running or self._overlay_focused or self._session is None:
            return
        if not self._manual:
            if self._detect_future is None:
                self._detect_token = object()
                retry_lookup = self._resolved_ref is None and monotonic() >= self._next_lookup_at
                self._detect_future = self._pool.submit(
                    self._detect, self._observed_epoch, self._detect_token, retry_lookup)
            self._invalidate_observed_changes()
            if self._detect_future.done():
                future = self._detect_future
                self._detect_future = None
                try:
                    observation, ref, stable, looked_up = future.result()
                except Exception:
                    self._session.pause()
                    self._session.resume()
                    self._observed_epoch = None
                    self._resolved_ref = None
                    self._title = None
                    self._result = None
                    self._status = "lookup_error"
                else:
                    if not stable or observation.epoch != self._observed_epoch or looked_up:
                        if observation.epoch != self._observed_epoch:
                            self._next_lookup_at = 0.0
                            self._lookup_delay = 3.0
                        self._session.update_current(observation, ref if stable else None)
                        self._observed_epoch = observation.epoch if stable else None
                        self._resolved_ref = ref if stable else None
                        self._title = observation.title if ref is not None and stable else None
                        self._result = None
                        self._next_read_at = 0.0
                        if stable and looked_up and ref is None:
                            self._next_lookup_at = monotonic() + self._lookup_delay
                            self._lookup_delay = min(self._lookup_delay * 2, 60.0)
                        elif ref is not None:
                            self._next_lookup_at = 0.0
                            self._lookup_delay = 3.0
                        self._status = ("ready" if ref is not None and stable else
                                        "looking_for_chat" if observation.page == "chat" else
                                        "accessibility_required" if observation.page == "permission_required"
                                        else "unidentified")

        if self._read_future is not None and self._read_future.done():
            future = self._read_future
            self._read_future = None
            try:
                item, observed = future.result()
            except Exception:
                self._status = "read_error"
            else:
                if self._session.current_ref and self._session.read_status:
                    self._status = self._session.read_status
                if (not self._manual and (observed is None or
                        observed.epoch != self._observed_epoch or observed.page != "chat")):
                    if observed is not None:
                        self._session.update_current(observed, None)
                    self._observed_epoch = None
                    self._resolved_ref = None
                    self._title = None
                    self._result = None
                    self._status = "unidentified"
                if item is not None and self._session.is_current(item.stamp):
                    self._result = None
                    self._status = "generating"
                    model = self._model
                    self._model_futures.append((item.stamp,
                        self._pool.submit(self._generate, item, model,
                                          observed.epoch if observed is not None else None, self._session)))

        if (self._resolved_ref is not None and self._read_future is None
                and monotonic() >= self._next_read_at):
            self._next_read_at = monotonic() + 3
            self._read_future = self._pool.submit(self._read_verified, self._observed_epoch, self._session)

        pending = []
        for stamp, future in self._model_futures:
            if not future.done():
                pending.append((stamp, future))
                continue
            try:
                result = future.result()
            except Exception:
                result = ResultBundle((), None, "internal_error")
            if result.error == "stale_result":
                continue
            if self._session.accept_result(stamp, result):
                self._result = result
                self._status = ("manual" if self._manual else "ready") if not result.error else result.error
        self._model_futures = pending

    def _invalidate_observed_changes(self):
        while True:
            try:
                token, observation = self._observations.get_nowait()
            except Empty:
                return
            if token is not self._detect_token:
                continue
            self._session.update_current(observation, None)
            self._observed_epoch = None
            self._resolved_ref = None
            self._title = None
            self._result = None
            self._read_future = None
            self._status = ("looking_for_chat" if observation.page == "chat" else
                            "accessibility_required" if observation.page == "permission_required" else "unidentified")

    def _detect(self, previous_epoch, token, retry_lookup=False):
        observation = self._probe.observe()
        if observation.epoch != previous_epoch:
            # Clear the previous chat on the UI thread before potentially slow CLI lookup.
            self._observations.put((token, observation))
        if observation.page != "chat" or (observation.epoch == previous_epoch and not retry_lookup):
            return observation, None, True, False
        resolved = self._lookup.candidates(observation)
        fresh = self._probe.observe()
        if fresh.epoch != observation.epoch:
            return fresh, None, False, True
        return resolved, self._resolver.resolve(resolved), True, True

    def _read_verified(self, expected_epoch, session):
        if expected_epoch is None:
            return session.tick(), None
        before = self._probe.observe()
        if before.epoch != expected_epoch or before.page != "chat":
            return None, before
        item = session.tick()
        after = self._probe.observe()
        return (item if after.epoch == expected_epoch else None), after

    def _generate(self, item: AnalysisInput, model: str, expected_epoch: int | None, session) -> ResultBundle:
        if not session.is_current(item.stamp):
            return ResultBundle((), None, "stale_result")
        verdict = None
        cloud_error = None
        try:
            verdict = self._judge.judge(item)
        except ModelError as error:
            cloud_error = str(error)
        if not session.is_current(item.stamp):
            return ResultBundle((), None, "stale_result")
        try:
            replies = tuple(self._generator.generate(item, model,
                                   should_continue=lambda: session.is_current(item.stamp)))
            if expected_epoch is not None and self._probe.observe().epoch != expected_epoch:
                return ResultBundle((), None, "stale_result")
            return ResultBundle(replies, verdict, cloud_error)
        except ModelError as error:
            return ResultBundle((), verdict, str(error))
