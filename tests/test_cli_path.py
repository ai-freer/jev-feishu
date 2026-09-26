import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.jev_feishu.chat_resolver import ChatResolver, LarkIdentityLookup
from src.jev_feishu.cli_path import lark_cli_path
from src.jev_feishu.diagnostics import Diagnostics
from src.jev_feishu.foreground import ChatObservation
from src.jev_feishu.lark_reader import LarkReader
from src.jev_feishu.types import ChatRef


class CliPathTests(unittest.TestCase):
    def test_home_fallback_finds_executable_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            binary = home / ".local" / "bin" / "lark-cli"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            with patch("src.jev_feishu.cli_path.shutil.which", return_value=None), \
                 patch("src.jev_feishu.cli_path.Path.home", return_value=home):
                self.assertEqual(lark_cli_path(), str(binary))

    def test_missing_cli_raises_without_local_installation(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch("src.jev_feishu.cli_path.shutil.which", return_value=None), \
             patch("src.jev_feishu.cli_path.Path.home", return_value=Path(tmp)), \
             patch("src.jev_feishu.cli_path.Path.is_file", return_value=False):
            with self.assertRaises(FileNotFoundError):
                lark_cli_path()

    def test_path_lookup_preferred(self):
        with patch("src.jev_feishu.cli_path.shutil.which", return_value="/fake/bin/lark-cli"):
            self.assertEqual(lark_cli_path(), "/fake/bin/lark-cli")


class FinderCliEnvironmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        node = root / "node"
        node.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        node.chmod(0o755)
        self.binary = root / "lark-cli"
        self.binary.write_text('''#!/usr/bin/env node
import json, sys
if "+chat-messages-list" in sys.argv:
    data = {"ok": True, "identity": "user", "data": {"messages": [{
        "message_id": "om_fixture", "sender": {"id": "ou_other"},
        "content": "虚构消息", "create_time": "1000", "msg_type": "text",
        "updated": False, "deleted": False}]}}
elif "+search-user" in sys.argv:
    data = {"ok": True, "data": {"users": [{"localized_name": "虚构对象", "p2p_chat_id": "oc_fixture"}]}}
elif "+chat-search" in sys.argv:
    data = {"ok": True, "data": {"chats": []}}
else:
    data = {"verified": True, "identities": {"user": {"status": "ready", "openId": "ou_self"}}}
print(json.dumps(data))
''')
        self.binary.chmod(0o755)
        environment = patch.dict(os.environ, {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_reader_runs_cli_interpreter_outside_finder_path(self):
        with patch("src.jev_feishu.lark_reader.lark_cli_path", return_value=str(self.binary)):
            messages = LarkReader().list_recent(ChatRef("chat", "oc_fixture"))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].text, "虚构消息")

    def test_identity_lookup_runs_cli_interpreter_outside_finder_path(self):
        observation = ChatObservation(1, "com.electron.lark", "chat", 1, (), "虚构对象", True)
        with patch("src.jev_feishu.chat_resolver.lark_cli_path", return_value=str(self.binary)):
            resolved = LarkIdentityLookup().candidates(observation)
        self.assertEqual(ChatResolver().resolve(resolved), ChatRef("chat", "oc_fixture"))

    def test_auth_check_runs_cli_interpreter_outside_finder_path(self):
        report = Diagnostics({"reply_model": "qwen3.5:4b", "ollama_base": "http://127.0.0.1:11434/v1",
                              "typesafe_key": ""}, cli_lookup=lambda: str(self.binary),
                             get=lambda *args: {"data": [{"id": "qwen3.5:4b"}]}).check()
        self.assertEqual(report.auth, "ready")
        self.assertEqual(report.own_id, "ou_self")
