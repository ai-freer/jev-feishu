"""One-page user-identity reader. Raw CLI output never escapes this adapter."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

from .cli_path import lark_cli_env, lark_cli_path
from .types import ChatRef, TextMessage
from .viewport import normalized


class ReaderError(RuntimeError):
    """Only fixed error categories may be shown by callers."""


def _string(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ReaderError("invalid_response")
    return value


def parse_messages(envelope: dict, *, latest_only=True, preserve_nontext=False) -> list[TextMessage]:
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        raise ReaderError("cli_error")
    if envelope.get("identity") != "user":
        raise ReaderError("wrong_identity")
    data = envelope.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ReaderError("invalid_response")
    if latest_only and data["messages"] and isinstance(data["messages"][0], dict):
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
        unsupported = msg_type != "text" or bool(item.get("thread_id"))
        if not deleted and unsupported and not preserve_nontext:
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
        if unsupported:
            result.append(TextMessage(message_id, sender_id, "", create_time, update_time, False))
            continue
        content = item.get("content")
        if not isinstance(content, str):
            raise ReaderError("invalid_response")
        if content.strip():
            result.append(TextMessage(message_id, sender_id, content, create_time, update_time, False))
    return result


class LarkReader:
    def __init__(self, runner=subprocess.run):
        self._runner = runner
        self._visible_cache = None

    def list_recent(self, ref: ChatRef, limit: int = 10) -> list[TextMessage]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid_page_size")
        flag = "--chat-id" if ref.kind == "chat" else "--user-id"
        command = [
            "im", "+chat-messages-list", "--as", "user",
            flag, ref.value, "--page-size", str(limit), "--order", "desc",
            "--no-reactions", "--json",
        ]
        return parse_messages(self._call(command), latest_only=False, preserve_nontext=True)

    def list_visible(self, ref, visible):
        if ref.kind != "chat":
            raise ReaderError("viewport_unmatched")
        if not visible:
            raise ReaderError("viewport_unmatched")
        target = visible[-1]
        if target.own:
            raise ReaderError("viewport_own")
        if not target.text.strip():
            raise ReaderError("viewport_nontext")
        key = (ref, tuple((r.token, r.text, r.own) for r in visible))
        cache = self._visible_cache
        if cache and cache[0] == key:
            return self._visible_history(ref, visible, target, cache[1])
        else:
            query = target.text.strip()[:80]
            if len(normalized(query)) < 2:
                raise ReaderError("viewport_unmatched")
            data = self._call(["im", "+messages-search", "--as", "user", "--chat-id", ref.value,
                               "--query", query, "--page-size", "50", "--no-reactions", "--json"])
            messages = parse_messages(data, latest_only=False)
            if (data["data"].get("has_more") is not False
                    or any(row.get("chat_id") != ref.value for row in data["data"]["messages"])):
                raise ReaderError("viewport_unmatched")
            exact = [m for m in messages if not m.deleted and normalized(m.text) == normalized(target.text)]
            if not 1 <= len(exact) <= 5:
                raise ReaderError("viewport_unmatched")
            matches = []
            for anchor in exact:
                try:
                    history = self._visible_history(ref, visible, target, anchor)
                except ReaderError as error:
                    if str(error) != "viewport_unmatched":
                        raise
                else:
                    matches.append((anchor, history))
            if len(matches) != 1:
                raise ReaderError("viewport_unmatched")
            anchor, history = matches[0]
            self._visible_cache = key, anchor
            return history

    def _visible_history(self, ref, visible, target, anchor):
        try:
            # The CLI may render local time to the minute. Include that minute,
            # then trim by verified ID, never by the rounded display timestamp.
            if anchor.create_time.isdigit():
                instant = datetime.fromtimestamp(int(anchor.create_time) / 1000, timezone.utc)
            else:
                instant = datetime.fromisoformat(anchor.create_time).astimezone()
            end = (instant + timedelta(minutes=1)).isoformat()
        except (ValueError, OverflowError, OSError):
            raise ReaderError("invalid_response") from None
        data = self._call(["im", "+chat-messages-list", "--as", "user", "--chat-id", ref.value,
                           "--end", end, "--page-size", "50", "--order", "desc", "--no-reactions", "--json"])
        messages = parse_messages(data, latest_only=False)
        if any(row.get("chat_id") != ref.value for row in data["data"]["messages"]):
            raise ReaderError("viewport_unmatched")
        indexes = [i for i, m in enumerate(messages) if m.message_id == anchor.message_id and not m.deleted
                   and normalized(m.text) == normalized(target.text)]
        if len(indexes) != 1:
            self._visible_cache = None
            raise ReaderError("viewport_unmatched")
        index = indexes[0]
        predecessors = [row for row in visible[:visible.index(target)] if row.text.strip()]
        if predecessors:
            previous = normalized(predecessors[-1].text)
            if not any(normalized(m.text) == previous and not m.deleted for m in messages[index + 1:]):
                raise ReaderError("viewport_unmatched")
        elif len(normalized(target.text)) < 12:
            raise ReaderError("viewport_unmatched")
        return messages[index:]

    def _call(self, command):
        try:
            binary = lark_cli_path()
        except FileNotFoundError:
            raise ReaderError("cli_unavailable") from None
        try:
            response = self._runner(
                [binary, *command], shell=False, timeout=15, capture_output=True, text=True,
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
        return envelope
