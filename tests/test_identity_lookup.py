from dataclasses import replace
import json
import subprocess
import unittest
from unittest.mock import Mock

from src.jev_feishu.chat_resolver import ChatResolver, LarkIdentityLookup
from src.jev_feishu.foreground import ChatObservation
from src.jev_feishu.types import ChatRef


def envelope(**data):
    return subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "data": data}), "")


def observed(title="虚构对象", page="chat", recipient=True):
    return ChatObservation(1, "com.electron.lark", page, 1, (), title, recipient)


class IdentityLookupTests(unittest.TestCase):
    def test_unique_exact_direct_chat_matches_api_chat_id(self):
        runner = Mock(side_effect=[
            envelope(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_direct"}], has_more=False),
            envelope(chats=[{"name": "含有虚构对象的群", "chat_mode": "group", "chat_id": "oc_group"}], has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(observed())
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_direct"))
        self.assertEqual(runner.call_count, 2)

    def test_direct_chat_survives_null_group_search_rows(self):
        runner = Mock(side_effect=[
            envelope(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_direct"}], has_more=False),
            envelope(chats=None, has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(observed())
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_direct"))

    def test_external_namesake_survives_null_group_search_rows(self):
        runner = Mock(side_effect=[
            envelope(users=[
                {"localized_name": "虚构对象", "p2p_chat_id": "oc_internal", "is_cross_tenant": False},
                {"localized_name": "虚构对象", "p2p_chat_id": "oc_external", "is_cross_tenant": True},
            ], has_more=False),
            envelope(chats=None, has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(replace(observed(), external=True))
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_external"))

    def test_null_user_search_rows_do_not_block_unique_group(self):
        runner = Mock(side_effect=[
            envelope(users=None, has_more=False),
            envelope(chats=[{"name": "虚构对象", "chat_mode": "DEFAULT", "chat_id": "oc_group"}],
                     has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(observed())
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_group"))

    def test_malformed_search_rows_do_not_confirm_identity(self):
        for user_rows, group_rows in (("invalid", []), ([], "invalid"), ([None], []), ([], [None])):
            with self.subTest(user_rows=user_rows, group_rows=group_rows):
                runner = Mock(side_effect=[
                    envelope(users=user_rows, has_more=False),
                    envelope(chats=group_rows, has_more=False),
                ])
                self.assertIsNone(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observed())))

    def test_missing_search_rows_do_not_confirm_identity(self):
        runner = Mock(side_effect=[
            envelope(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_direct"}], has_more=False),
            envelope(has_more=False),
        ])
        self.assertIsNone(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observed())))

    def test_unique_exact_group_chat_matches_api_chat_id(self):
        runner = Mock(side_effect=[
            envelope(users=[], has_more=False),
            envelope(chats=[{"name": "虚构对象", "chat_mode": "group", "chat_id": "oc_group"}], has_more=False),
        ])
        self.assertEqual(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observed())),
                         ChatRef("chat", "oc_group"))

    def test_search_default_mode_resolves_verified_ordinary_group(self):
        runner = Mock(side_effect=[
            envelope(users=[], has_more=False),
            envelope(chats=[{"name": "虚构对象", "chat_mode": "DEFAULT",
                             "chat_id": "oc_group", "chat_status": "normal"}], has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(observed())
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_group"))
        group_command = runner.call_args_list[1].args[0]
        self.assertEqual(group_command[group_command.index("--chat-modes") + 1], "group")

    def test_unknown_and_non_group_modes_remain_unresolved(self):
        for mode in (None, "unknown", "default", "topic", "p2p"):
            with self.subTest(mode=mode):
                runner = Mock(side_effect=[
                    envelope(users=[], has_more=False),
                    envelope(chats=[{"name": "虚构对象", "chat_mode": mode,
                                     "chat_id": "oc_group"}], has_more=False),
                ])
                self.assertIsNone(ChatResolver().resolve(
                    LarkIdentityLookup(runner).candidates(observed())))

    def test_same_name_and_incomplete_search_fail_closed(self):
        for user_data,group_data in (
            (dict(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_a"},
                         {"localized_name": "虚构对象", "p2p_chat_id": "oc_b"}], has_more=False),
             dict(chats=[], has_more=False)),
            (dict(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_a"}], has_more=True),
             dict(chats=[], has_more=False)),
            (dict(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_a"}], has_more=False),
             dict(chats=[{"name": "虚构对象", "chat_mode": "group", "chat_id": "oc_g"}], has_more=False)),
        ):
            runner = Mock(side_effect=[envelope(**user_data), envelope(**group_data)])
            self.assertIsNone(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observed())))

    def test_nonchat_and_missing_recipient_do_not_search(self):
        runner = Mock()
        lookup = LarkIdentityLookup(runner)
        self.assertIsNone(ChatResolver().resolve(lookup.candidates(observed(page="other"))))
        self.assertIsNone(ChatResolver().resolve(lookup.candidates(observed(recipient=False))))
        runner.assert_not_called()

    def test_cli_error_never_becomes_verified_identity(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 1, "", "private"))
        self.assertIsNone(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observed())))

    def test_explicit_external_badge_disambiguates_internal_namesake(self):
        runner = Mock(side_effect=[
            envelope(users=[
                {"localized_name": "虚构对象", "p2p_chat_id": "oc_internal", "is_cross_tenant": False},
                {"localized_name": "虚构对象", "p2p_chat_id": "oc_external", "is_cross_tenant": True},
            ], has_more=False),
            envelope(chats=[], has_more=False),
        ])
        observation = replace(observed(), external=True)
        result = LarkIdentityLookup(runner).candidates(observation)
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_external"))

    def test_explicit_external_group_badge_excludes_internal_namesake(self):
        runner = Mock(side_effect=[
            envelope(users=[], has_more=False),
            envelope(chats=[
                {"name": "虚构对象", "chat_mode": "DEFAULT", "chat_id": "oc_internal", "external": False},
                {"name": "虚构对象", "chat_mode": "DEFAULT", "chat_id": "oc_external", "external": True},
            ], has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(replace(observed(), external=True))
        self.assertEqual(ChatResolver().resolve(result), ChatRef("chat", "oc_external"))

    def test_external_badge_never_guesses_unknown_flags_or_same_kind_namesakes(self):
        for flag in (None, "false", "true", 0, 1, True):
            with self.subTest(flag=flag):
                runner = Mock(side_effect=[
                    envelope(users=[
                        {"localized_name": "虚构对象", "p2p_chat_id": "oc_a", "is_cross_tenant": True},
                        {"localized_name": "虚构对象", "p2p_chat_id": "oc_b", "is_cross_tenant": flag},
                    ], has_more=False),
                    envelope(chats=[], has_more=False),
                ])
                result = LarkIdentityLookup(runner).candidates(replace(observed(), external=True))
                self.assertIsNone(ChatResolver().resolve(result))

    def test_external_person_and_external_group_with_same_name_remain_ambiguous(self):
        runner = Mock(side_effect=[
            envelope(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_person", "is_cross_tenant": True}], has_more=False),
            envelope(chats=[{"name": "虚构对象", "chat_mode": "DEFAULT", "chat_id": "oc_group", "external": True}], has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(replace(observed(), external=True))
        self.assertIsNone(ChatResolver().resolve(result))

    def test_absent_badge_does_not_imply_internal_chat(self):
        runner = Mock(side_effect=[
            envelope(users=[
                {"localized_name": "虚构对象", "p2p_chat_id": "oc_a", "is_cross_tenant": True},
                {"localized_name": "虚构对象", "p2p_chat_id": "oc_b", "is_cross_tenant": False},
            ], has_more=False),
            envelope(chats=[], has_more=False),
        ])
        self.assertIsNone(ChatResolver().resolve(LarkIdentityLookup(runner).candidates(observed())))

    def test_unknown_group_flag_cannot_remove_an_exact_namesake(self):
        runner = Mock(side_effect=[
            envelope(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_person", "is_cross_tenant": True}], has_more=False),
            envelope(chats=[{"name": "虚构对象", "chat_mode": "DEFAULT", "chat_id": "oc_group"}], has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(replace(observed(), external=True))
        self.assertIsNone(ChatResolver().resolve(result))

    def test_external_badge_does_not_bypass_incomplete_search(self):
        runner = Mock(side_effect=[
            envelope(users=[{"localized_name": "虚构对象", "p2p_chat_id": "oc_person", "is_cross_tenant": True}], has_more=True),
            envelope(chats=[], has_more=False),
        ])
        result = LarkIdentityLookup(runner).candidates(replace(observed(), external=True))
        self.assertIsNone(ChatResolver().resolve(result))
