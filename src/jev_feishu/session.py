"""Generation-safe session controller. No message is stored across processes."""

from dataclasses import dataclass
from threading import RLock
from time import monotonic

from .chat_resolver import ChatResolver
from .foreground import ChatObservation
from .lark_reader import ReaderError
from .types import ChatRef


@dataclass(frozen=True, repr=False)
class VersionStamp:
    observation_epoch: int
    chat_ref: ChatRef
    message_id: str
    update_time: str | None


@dataclass(frozen=True, repr=False)
class AnalysisInput:
    stamp: VersionStamp
    text: str
    context: tuple[str, ...]


class SessionController:
    def __init__(self, reader, own_sender_id: str, clock=monotonic):
        if not own_sender_id:
            raise ValueError("own_sender_id_required")
        self._reader = reader
        self._resolver = ChatResolver()
        self._own_sender_id = own_sender_id
        self._clock = clock
        self._lock = RLock()
        self._epoch = 0
        self._observation_epoch = -1
        self._ref: ChatRef | None = None
        self._active = False
        self._paused = True
        self._manual = False
        self._overlay_focused = False
        self._next_poll = 0.0
        self._failure_count = 0
        self._last_key: tuple[str, str | None] | None = None
        self._stamp: VersionStamp | None = None
        self._candidate: object | None = None
        self._read_status: str | None = None
        self._follow_mode = "latest"
        self._visible_messages = ()
        self._settle_at = 0.0
        self._target_text = ""

    @property
    def target_text(self):
        with self._lock:
            return self._target_text

    def set_follow_mode(self, mode):
        if mode not in ("latest", "visible"):
            raise ValueError("invalid_follow_mode")
        with self._lock:
            self._follow_mode = mode
            self._invalidate()

    @property
    def read_status(self):
        with self._lock:
            return self._read_status

    @property
    def candidate(self):
        with self._lock:
            return self._candidate

    @property
    def current_ref(self) -> ChatRef | None:
        with self._lock:
            return self._ref if self._active else None

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._manual = False
            self._invalidate()
            self._active = False
            self._ref = None

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._manual = False
            self._invalidate()
            self._active = False
            self._ref = None

    def refresh_current(self) -> bool:
        with self._lock:
            if not self._active or self._paused or self._ref is None:
                return False
            self._invalidate()
            return True

    def set_overlay_focused(self, focused: bool) -> None:
        with self._lock:
            if self._overlay_focused != focused:
                self._overlay_focused = focused
                if focused:
                    # Editing is allowed, but old in-flight work cannot replace it.
                    self._stamp = None
                else:
                    self._invalidate()

    def _invalidate(self) -> None:
        self._epoch += 1
        self._target_text = ""
        self._candidate = None
        self._stamp = None
        self._last_key = None
        self._next_poll = 0.0
        self._failure_count = 0
        self._read_status = None

    def update_current(self, observation: ChatObservation, ref: ChatRef | None) -> None:
        with self._lock:
            if self._manual:
                return
            if self._overlay_focused:
                return
            if observation.epoch < self._observation_epoch:
                return
            changed_observation = observation.epoch != self._observation_epoch
            self._observation_epoch = observation.epoch
            active = (not self._paused
                      and observation.frontmost_bundle == "com.electron.lark"
                      and observation.page == "chat" and ref is not None
                      and self._resolver.resolve(observation) == ref)
            if not active:
                if self._active or self._ref is not None or self._stamp is not None:
                    self._invalidate()
                self._active = False
                self._ref = None
                return
            if not self._active or self._ref != ref or changed_observation:
                self._invalidate()
                self._settle_at = self._clock() + 0.8
            self._visible_messages = observation.visible_messages
            self._active = True
            self._ref = ref

    def enter_manual(self, ref: ChatRef) -> None:
        with self._lock:
            self._manual = True
            self._paused = False
            self._overlay_focused = False
            self._invalidate()
            self._active = True
            self._ref = ref

    def tick(self) -> AnalysisInput | None:
        with self._lock:
            if not self._active or self._paused or self._overlay_focused or self._ref is None:
                return None
            now = self._clock()
            visible = self._follow_mode == "visible" and not self._manual
            snapshot = self._visible_messages
            if visible and (not snapshot or now < self._settle_at):
                self._read_status = "viewport_unmatched" if not snapshot else "viewport_settling"
                return None
            if now < self._next_poll:
                return None
            ref, epoch = self._ref, self._epoch
            self._next_poll = now + 3
        try:
            messages = (self._reader.list_visible(ref, snapshot) if visible
                        else self._reader.list_recent(ref))
        except ReaderError as error:
            with self._lock:
                if (self._active and self._ref == ref and self._epoch == epoch
                        and not self._paused and not self._overlay_focused):
                    self._failure_count += 1
                    self._next_poll = self._clock() + min(3 * (2 ** (self._failure_count - 1)), 60)
                    self._read_status = (str(error) if visible and str(error) in
                        ("viewport_own", "viewport_nontext") else "viewport_unmatched" if visible else "read_error")
                    self._target_text = ""
                    self._candidate = None
                    self._stamp = None
                    self._last_key = None
            return None
        with self._lock:
            if (not self._active or self._ref != ref or self._epoch != epoch
                    or self._paused or self._overlay_focused):
                return None
            self._failure_count = 0
            self._read_status = None
            self._next_poll = self._clock() + 3
            if self._stamp is not None:
                current = next((m for m in messages if m.message_id == self._stamp.message_id), None)
                if current is not None and (current.deleted or current.update_time != self._stamp.update_time):
                    self._candidate = None
                    self._stamp = None
            if not messages or messages[0].deleted or messages[0].sender_id == self._own_sender_id:
                self._target_text = ""
                self._candidate = None
                self._stamp = None
                self._read_status = ("no_text" if not messages else
                                     "message_deleted" if messages[0].deleted else "own_message")
                return None
            incoming = [m for m in messages if not m.deleted and m.sender_id != self._own_sender_id]
            if not incoming:
                return None
            latest = incoming[0]
            self._target_text = latest.text
            key = (latest.message_id, latest.update_time)
            if self._last_key == key:
                return None
            self._last_key = key
            stamp = VersionStamp(epoch, ref, *key)
            self._stamp = stamp
            self._candidate = None
            context = tuple(m.text for m in messages if not m.deleted and m.message_id != latest.message_id)[:2]
            return AnalysisInput(stamp, latest.text, context)

    def accept_result(self, stamp: VersionStamp, candidate: object) -> bool:
        with self._lock:
            if not self.is_current(stamp):
                return False
            self._candidate = candidate
            return True

    def is_current(self, stamp: VersionStamp) -> bool:
        with self._lock:
            return (self._active and not self._paused and not self._overlay_focused
                    and self._stamp == stamp and self._epoch == stamp.observation_epoch
                    and self._ref == stamp.chat_ref)
