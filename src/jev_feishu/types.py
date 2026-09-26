"""In-memory message identities; representations deliberately omit user data."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, repr=False)
class ChatRef:
    kind: Literal["chat", "user"]
    value: str

    def __post_init__(self):
        if self.kind not in ("chat", "user"):
            raise ValueError("invalid_chat_kind")
        prefix = "oc_" if self.kind == "chat" else "ou_"
        if not isinstance(self.value, str) or not self.value.startswith(prefix):
            raise ValueError("invalid_chat_reference")
        suffix = self.value[len(prefix):]
        if not suffix or not suffix.isascii() or not suffix.isalnum():
            raise ValueError("invalid_chat_reference")


@dataclass(frozen=True, repr=False)
class TextMessage:
    message_id: str
    sender_id: str
    text: str
    create_time: str
    update_time: str | None
    deleted: bool
