"""Six local reply candidates; one two-line request per selected tone."""

import re

from .http_client import ModelError, post_json
from .session import AnalysisInput


TONES = {
    "高情商话术": "先接住情绪，再说事实和下一步；简短、真诚，不说教。",
    "贴吧老哥": "口语化，可自嘲玩梗，但不骂人，不用书面客套。",
    "稳如老狗": "直接给结论和时间点，短句，不铺垫。",
}


def _parse_lines(raw: str) -> list[str]:
    lines = []
    for line in raw.splitlines():
        value = re.sub(r"^\s*(?:[-*]|\d+[.、])\s*", "", line).strip(" \t\"'“”")
        if value and value not in lines:
            lines.append(value)
    return lines[:2]


class ReplyGenerator:
    def __init__(self, base: str = "http://127.0.0.1:11434/v1", transport=post_json):
        if base.rstrip("/") != "http://127.0.0.1:11434/v1":
            raise ValueError("nonlocal_ollama_url")
        self._url = base.rstrip("/") + "/chat/completions"
        self._transport = transport

    def generate(self, item: AnalysisInput, model: str = "qwen3.5:4b", should_continue=lambda: True) -> list[str]:
        if model not in ("qwen3.5:4b", "qwen3.5:9b"):
            raise ValueError("unsupported_reply_model")
        context = "\n".join(reversed(item.context))
        candidates = []
        for tone, instruction in TONES.items():
            if not should_continue():
                raise ModelError("stale_result")
            prompt = (f"刚收到一条飞书消息：{item.text}\n"
                      f"前文：{context}\n" if context else f"刚收到一条飞书消息：{item.text}\n")
            prompt += (f"请写两条{tone}风格的可编辑回复。{instruction}"
                       "第一条稳妥，第二条语气更鲜明；每条不超过30字。"
                       "只输出两行回复，不编号、不解释。")
            payload = {
                "model": model, "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300, "temperature": 0.9, "reasoning_effort": "none",
                "stream": False,
            }
            try:
                data = self._transport(self._url, {"content-type": "application/json",
                                 "authorization": "Bearer ollama"}, payload, 45)
                message = data["choices"][0]["message"]
                raw = message.get("content") or ""
                if not raw.strip() and (message.get("reasoning") or message.get("reasoning_content")):
                    raise ModelError("thinking_only")
                lines = _parse_lines(raw)
                if len(lines) != 2:
                    raise ModelError("insufficient_candidates")
                candidates.extend(lines)
            except (KeyError, IndexError, TypeError, AttributeError):
                raise ModelError("invalid_response") from None
        return candidates
