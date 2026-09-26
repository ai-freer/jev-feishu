import unittest

from src.jev_feishu.chat_resolver import ChatResolver
from src.jev_feishu.foreground import ChatEvidence, ChatObservation
from src.jev_feishu.types import ChatRef


LARK = "com.electron.lark"
A = ChatRef("chat", "oc_fakea")
B = ChatRef("user", "ou_fakeb")


def observed(epoch=1, bundle=LARK, page="chat", windows=1, candidates=()):
    return ChatObservation(epoch, bundle, page, windows, candidates, "虚构对象", True)


class ResolverTests(unittest.TestCase):
    def test_verified_selection_resolves_group_and_direct_chat(self):
        resolver = ChatResolver()
        for ref in (A, B):
            obs = observed(candidates=(ChatEvidence(ref, True, True),))
            self.assertEqual(resolver.resolve(obs), ref)

    def test_ambiguous_title_or_search_candidate_cannot_resolve(self):
        resolver = ChatResolver()
        for candidates in (
            (),
            (ChatEvidence(A, False, True),),
            (ChatEvidence(A, True, False),),
            (ChatEvidence(A, True, True), ChatEvidence(B, True, True)),
            (ChatEvidence(A, True, True), ChatEvidence(B, True, False)),
        ):
            with self.subTest(candidates=len(candidates)):
                self.assertIsNone(resolver.resolve(observed(candidates=candidates)))

    def test_nonchat_foreground_and_multiple_windows_fail_closed(self):
        candidate = (ChatEvidence(A, True, True),)
        resolver = ChatResolver()
        for kwargs in ({"bundle": "other"}, {"page": "unknown"},
                       {"page": "other"}, {"windows": 0}, {"windows": 2}):
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(resolver.resolve(observed(candidates=candidate, **kwargs)))
