"""Measure installed local reply generation without reading real chats or config."""

import json
from pathlib import Path
from time import monotonic

import jev_feishu.replies
from jev_feishu.http_client import ModelError, get_json
from jev_feishu.replies import ReplyGenerator
from jev_feishu.session import AnalysisInput, VersionStamp
from jev_feishu.types import ChatRef


def is_loaded(model):
    data = get_json("http://127.0.0.1:11434/api/ps", 5)
    entries = data.get("models")
    if not isinstance(entries, list):
        raise ModelError("invalid_response")
    return any(isinstance(entry, dict) and entry.get("name") == model for entry in entries)


def main():
    installed = Path("/Applications/Jev 飞书助手.app/Contents/lib/python3.12/site-packages/jev_feishu")
    assert Path(jev_feishu.replies.__file__).resolve().is_relative_to(installed)
    item = AnalysisInput(VersionStamp(0, ChatRef("chat", "oc_performance"), "om_performance", None),
                         "虚构性能测试：明天下午方便同步一下项目进展吗？", ())
    generator = ReplyGenerator()
    for model in ("qwen3.5:4b", "qwen3.5:9b"):
        for attempt in (1, 2):
            loaded = is_loaded(model)
            started = monotonic()
            count, status = 0, "ready"
            try:
                count = len(generator.generate(item, model))
            except ModelError as error:
                status = str(error)
            elapsed = monotonic() - started
            loaded_after = is_loaded(model)
            print(json.dumps({"model": model, "attempt": attempt,
                              "loaded_before": loaded, "loaded_after": loaded_after,
                              "elapsed_seconds": round(elapsed, 2),
                              "candidate_count": count, "status": status}), flush=True)


if __name__ == "__main__":
    main()
