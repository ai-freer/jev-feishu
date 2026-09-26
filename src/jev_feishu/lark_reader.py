"""One-page user-identity reader. Raw CLI output never escapes this adapter."""

import json
import subprocess

from .cli_path import lark_cli_env, lark_cli_path
from .types import ChatRef, TextMessage


class ReaderError(RuntimeError):
    """Only fixed error categories may be shown by callers."""


def _string(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ReaderError("invalid_response")
    return value


def parse_messages(envelope: dict) -> list[TextMessage]:
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        raise ReaderError("cli_error")
    if envelope.get("identity") != "user":
        raise ReaderError("wrong_identity")
    data = envelope.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ReaderError("invalid_response")
    if data["messages"] and isinstance(data["messages"][0], dict):
        latest = data["messages"][0]
        if latest.get("deleted") is False:
            if _string(latest, "msg_type") != "text" or latest.get("thread_id"):
                return []
            if isinstance(latest.get("content"), str) and not latest["content"].strip():
                return []
    result = []
    for item in data["messages"]:
        if not isinstance(item, dict):
            raise ReaderError("invalid_response")
        deleted = item.get("deleted")
        if type(deleted) is not bool:
            raise ReaderError("invalid_response")
        msg_type = _string(item, "msg_type")
        if type(item.get("updated")) is not bool:
            raise ReaderError("invalid_response")
        # Tombstones must survive filtering so callers can invalidate old replies.
        if not deleted and (msg_type != "text" or item.get("thread_id")):
            continue
        message_id = _string(item, "message_id")
        create_time = _string(item, "create_time")
        update_time = item.get("update_time")
        if update_time is not None and (not isinstance(update_time, str) or not update_time):
            raise ReaderError("invalid_response")
        if item.get("updated") is True and not update_time:
            raise ReaderError("edit_version_missing")
        if deleted:
            result.append(TextMessage(message_id, "", "", create_time, update_time, True))
            continue
        sender = item.get("sender")
        if not isinstance(sender, dict):
            raise ReaderError("invalid_response")
        sender_id = _string(sender, "id")
        content = item.get("content")
        if not isinstance(content, str):
            raise ReaderError("invalid_response")
        if content.strip():
            result.append(TextMessage(message_id, sender_id, content, create_time, update_time, False))
    return result


class LarkReader:
    def __init__(self, runner=subprocess.run):
        self._runner = runner

    def list_recent(self, ref: ChatRef, limit: int = 10) -> list[TextMessage]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid_page_size")
        flag = "--chat-id" if ref.kind == "chat" else "--user-id"
        try:
            binary = lark_cli_path()
        except FileNotFoundError:
            raise ReaderError("cli_unavailable") from None
        command = [
            binary, "im", "+chat-messages-list", "--as", "user",
            flag, ref.value, "--page-size", str(limit), "--order", "desc",
            "--no-reactions", "--json",
        ]
        try:
            response = self._runner(
                command, shell=False, timeout=15, capture_output=True, text=True,
                env=lark_cli_env(binary),
            )
        except subprocess.TimeoutExpired:
            raise ReaderError("timeout") from None
        except OSError:
            raise ReaderError("cli_unavailable") from None
        if response.returncode != 0:
            raise ReaderError("cli_error")
        try:
            envelope = json.loads(response.stdout)
        except (ValueError, TypeError):
            raise ReaderError("invalid_response") from None
        return parse_messages(envelope)
