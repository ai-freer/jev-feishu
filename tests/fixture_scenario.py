"""Fictional API boundaries shared by integration and manual packaged-HUD checks."""

from contextlib import ExitStack
from importlib import import_module
import json
import subprocess
from unittest.mock import patch


class FixtureScenario:
    def __init__(self, package="src.jev_feishu"):
        self.package = package
        self.chat = "a"
        self.epoch = 1
        self.page = "chat"
        self.authorized = True
        self.deleted = False
        self.revision = 0
        self.local_error = None
        self.cloud_error = None
        self.model_calls = []
        self.read_count = 0
        self.config = {"reply_model": "qwen3.5:4b", "ollama_base": "http://127.0.0.1:11434/v1",
                       "typesafe_base": "https://openrouter.ai/api", "typesafe_key": "fictional-test-key",
                       "typesafe_model": "~typesafe/jev-latest"}
        self._patches = ExitStack()
        for module in ("lark_reader", "chat_resolver"):
            self._patches.enter_context(patch(f"{package}.{module}.lark_cli_path", return_value="fixture-cli"))

    @property
    def title(self):
        return "虚构单聊 A" if self.chat == "a" else "虚构普通群 B"

    def module(self, name):
        return import_module(f"{self.package}.{name}")

    def observe(self):
        return self.module("foreground").ChatObservation(
            self.epoch, "com.electron.lark" if self.page == "chat" else "fixture.other",
            self.page, 1, (), self.title if self.page == "chat" else None, self.page == "chat")

    def switch(self, chat):
        self.chat, self.page = chat, "chat"
        self.deleted = False
        self.revision = 0
        self.epoch += 1

    def leave(self):
        self.page = "unknown"
        self.epoch += 1

    def runner(self, command, **kwargs):
        if command[1:3] == ["auth", "status"]:
            data = {"verified": self.authorized, "identities": {"user": {
                "status": "ready" if self.authorized else "needs_refresh", "openId": "ou_fixture_self"}}}
        elif "+search-user" in command:
            data = {"ok": True, "data": {"has_more": False, "users": [
                {"localized_name": self.title, "p2p_chat_id": "oc_fixturea"}] if self.chat == "a" else []}}
        elif "+chat-search" in command:
            data = {"ok": True, "data": {"has_more": False, "chats": [
                {"name": self.title, "chat_mode": "group", "chat_id": "oc_fixtureb"}] if self.chat == "b" else []}}
        elif "+chat-messages-list" in command:
            assert "--as" in command and command[command.index("--as") + 1] == "user"
            assert command[command.index("--chat-id") + 1] == f"oc_fixture{self.chat}"
            self.read_count += 1
            message = {"message_id": f"om_fixture_{self.chat}", "msg_type": "text",
                       "create_time": "1000", "deleted": self.deleted, "updated": bool(self.revision),
                       "sender": {"id": "ou_fixture_other"},
                       "content": f"虚构验收消息 {self.chat}：项目进展如何？"}
            if self.revision:
                message["update_time"] = str(2000 + self.revision)
            data = {"ok": True, "identity": "user", "data": {"messages": [message]}}
        else:
            raise AssertionError("unexpected fixture CLI operation")
        return subprocess.CompletedProcess(command, 0, json.dumps(data), "")

    def transport(self, url, headers, payload, timeout):
        kind = "jev" if url.endswith("/systemone") else "ollama"
        self.model_calls.append((kind, payload["model"]))
        error = self.cloud_error if kind == "jev" else self.local_error
        if error:
            raise self.module("http_client").ModelError(error)
        if kind == "jev":
            assert payload["state"].startswith("虚构")
            return {"answers": {"intent": {"choice": "问进度", "confidence": 0.9}, "risk": {"score": 1}}}
        assert url == "http://127.0.0.1:11434/v1/chat/completions"
        assert payload["reasoning_effort"] == "none"
        assert [message["role"] for message in payload["messages"]] == ["system", "user"]
        assert json.loads(payload["messages"][1]["content"])["latest_message"].startswith("虚构")
        serial = len(self.model_calls)
        return {"choices": [{"message": {"content": f"虚构候选 {serial}：稍后给你进展。\n虚构候选 {serial}：今天整理后同步。"}}]}

    def make_runtime(self, executor=None):
        gate = self.module("privacy").PrivacyGate(self.config.get("jev_enabled", True))
        return self.module("runtime").AppRuntime(
            own_id="ou_fixture_self", probe=self,
            lookup=self.module("chat_resolver").LarkIdentityLookup(self.runner),
            reader=self.module("lark_reader").LarkReader(self.runner), gate=gate,
            judge=self.module("jev").JevJudge(self.config["typesafe_base"], self.config["typesafe_key"],
                                              self.config["typesafe_model"], gate, self.transport),
            generator=self.module("replies").ReplyGenerator(transport=self.transport),
            diagnostics=self.module("diagnostics").Diagnostics(self.config, runner=self.runner,
                cli_lookup=lambda: "fixture-cli", post=self.transport,
                get=lambda *args: {"data": [{"id": "qwen3.5:4b"}, {"id": "qwen3.5:9b"}]}),
            executor=executor, config=self.config, save_jev_setting=lambda enabled: None,
            save_tones=lambda tones: None)

    def close(self):
        self._patches.close()
