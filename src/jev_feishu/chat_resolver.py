"""Fail-closed mapping from observed selected chat to a verified API reference."""

import json
import subprocess
from dataclasses import replace

from .cli_path import lark_cli_env, lark_cli_path
from .foreground import ChatEvidence, ChatObservation
from .types import ChatRef


class ChatResolver:
    def resolve(self, observation: ChatObservation) -> ChatRef | None:
        if (observation.frontmost_bundle != "com.electron.lark"
                or observation.page != "chat" or observation.window_count != 1
                or not observation.recipient_matches_title or not observation.title):
            return None
        selected = [item.ref for item in observation.candidates
                    if item.selected and item.api_confirmed]
        if len(selected) != 1:
            return None
        if any(item.selected and not item.api_confirmed for item in observation.candidates):
            return None
        return selected[0]


class LarkIdentityLookup:
    """Look up exact visible titles, never list or read candidate messages."""

    def __init__(self, runner=subprocess.run):
        self._runner = runner

    def candidates(self, observation: ChatObservation) -> ChatObservation:
        if (observation.frontmost_bundle != "com.electron.lark" or observation.page != "chat"
                or observation.window_count != 1 or not observation.recipient_matches_title
                or not observation.title or len(observation.title) > 50):
            return observation
        title = observation.title
        def call(args):
            try:
                args[0] = lark_cli_path()
                result = self._runner(args, shell=False, capture_output=True, text=True,
                                      timeout=15, env=lark_cli_env(args[0]))
                data = json.loads(result.stdout)
                if result.returncode != 0 or data.get("ok") is not True:
                    return None
                return data.get("data") if isinstance(data.get("data"), dict) else None
            except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                return None

        users = call(["lark-cli", "contact", "+search-user", "--as", "user", "--query",
                      title, "--has-chatted", "--page-size", "30", "--json"])
        groups = call(["lark-cli", "im", "+chat-search", "--as", "user", "--query",
                       title, "--disable-search-by-user", "--chat-modes", "group",
                       "--page-size", "100", "--json"])
        if users is None or groups is None or users.get("has_more") or groups.get("has_more"):
            return observation
        if "users" not in users or "chats" not in groups:
            return observation
        user_rows, group_rows = users["users"], groups["chats"]
        if (user_rows is not None and not isinstance(user_rows, list)
                or group_rows is not None and not isinstance(group_rows, list)):
            return observation
        user_rows, group_rows = user_rows or [], group_rows or []
        if any(not isinstance(row, dict) for row in (*user_rows, *group_rows)):
            return observation
        exact_users = [user for user in user_rows
                       if user.get("localized_name") == title]
        exact_groups = [chat for chat in group_rows
                        if chat.get("name") == title]
        if observation.external is True:
            # Missing flags must not silently remove a possible namesake.
            if (any(type(user.get("is_cross_tenant")) is not bool for user in exact_users)
                    or any(type(chat.get("external")) is not bool for chat in exact_groups)):
                return observation
            exact_users = [user for user in exact_users if user["is_cross_tenant"]]
            exact_groups = [chat for chat in exact_groups if chat["external"]]
        refs = []
        for user in exact_users:
            if user.get("p2p_chat_id"):
                try:
                    refs.append(ChatRef("chat", user["p2p_chat_id"]))
                except ValueError:
                    return observation
        for chat in exact_groups:
            # v2 search reports DEFAULT for the ordinary groups selected above.
            if chat.get("chat_mode") in ("group", "DEFAULT"):
                try:
                    refs.append(ChatRef("chat", chat["chat_id"]))
                except (KeyError, ValueError):
                    return observation
        if len(refs) != 1:
            return observation
        return replace(observation, candidates=(ChatEvidence(refs[0], True, True),))
