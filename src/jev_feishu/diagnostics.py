"""Bounded dependency checks and explicitly requested fictional model tests."""

from dataclasses import dataclass, field
import json
import subprocess
from time import monotonic

from .cli_path import lark_cli_env, lark_cli_path
from .http_client import ModelError, get_json, post_json
from .jev import JevJudge, endpoint
from .privacy import PrivacyGate
from .replies import ReplyGenerator
from .session import AnalysisInput, VersionStamp
from .types import ChatRef


STATUS_LABELS = {
    "ready": "可用", "missing": "未找到", "unavailable": "未授权或授权已过期",
    "configured": "已配置（尚未测试连接）", "not_configured": "未配置",
    "connection_error": "连接失败或超时", "http_error": "服务返回错误",
    "invalid_response": "服务响应无效", "model_missing": "未安装所选模型",
    "unauthorized": "认证失败", "rate_limited": "请求受限",
    "thinking_only": "只返回思考内容", "insufficient_candidates": "候选数量不足",
    "internal_error": "检查失败", "unchecked": "尚未检查",
}


@dataclass(frozen=True)
class DependencyReport:
    cli: str
    auth: str
    ollama: str
    jev: str
    available_models: tuple[str, ...] = ()
    own_id: str | None = field(default=None, repr=False)

    def summary(self) -> str:
        rows = (("飞书 CLI", self.cli), ("飞书用户授权", self.auth),
                ("Ollama", self.ollama), ("Jev", self.jev))
        return "\n".join(f"{name}：{STATUS_LABELS.get(status, '检查失败')}" for name, status in rows)


@dataclass(frozen=True)
class ConnectionTest:
    target: str
    model: str
    status: str
    elapsed: float
    candidate_count: int = 0

    def summary(self) -> str:
        label = STATUS_LABELS.get(self.status, "检查失败")
        count = f"，{self.candidate_count} 条候选" if self.candidate_count else ""
        return f"{self.model}：{label}{count}，{self.elapsed:.2f} 秒"


class Diagnostics:
    def __init__(self, config, *, cli_lookup=lark_cli_path, runner=subprocess.run,
                 get=get_json, post=post_json):
        self._config = config
        self._cli_lookup = cli_lookup
        self._runner = runner
        self._get = get
        self._post = post

    def configuration_text(self, model: str) -> str:
        try:
            cloud_url = endpoint(self._config["typesafe_base"])
        except ValueError:
            cloud_url = "配置地址无效"
        return (f"本机回复地址：{self._config['ollama_base']}\n"
                f"当前回复模型：{model}\n"
                f"Jev 地址：{cloud_url}\n"
                f"Jev 模型：{self._config['typesafe_model']}\n"
                f"Jev 密钥：{'已配置' if self._config['typesafe_key'] else '未配置'}")

    def check(self) -> DependencyReport:
        own_id = None
        cli, auth = "missing", "unavailable"
        try:
            binary = self._cli_lookup()
            cli = "ready"
            response = self._runner([binary, "auth", "status", "--json", "--verify"],
                shell=False, capture_output=True, text=True, timeout=15,
                env=lark_cli_env(binary))
            data = json.loads(response.stdout)
            user = data["identities"]["user"]
            value = user["openId"]
            if (response.returncode == 0 and data.get("verified") is True
                    and user.get("status") == "ready" and isinstance(value, str)
                    and value.startswith("ou_")):
                own_id, auth = value, "ready"
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
            pass
        models = ()
        try:
            # Inventory only: no model prompt or chat content is sent at startup.
            data = self._get(self._config["ollama_base"].rstrip("/") + "/models", 5)
            entries = data["data"]
            if not isinstance(entries, list):
                raise ModelError("invalid_response")
            models = tuple(model for model in ("qwen3.5:4b", "qwen3.5:9b")
                           if any(isinstance(entry, dict) and entry.get("id") == model for entry in entries))
            ollama = "ready" if self._config["reply_model"] in models else "model_missing"
        except ModelError as error:
            ollama = str(error) if str(error) in STATUS_LABELS else "internal_error"
        except (KeyError, TypeError):
            ollama = "invalid_response"
        return DependencyReport(cli, auth, ollama,
            "configured" if self._config["typesafe_key"] else "not_configured", models, own_id)

    def test_connection(self, target: str, model: str) -> ConnectionTest:
        if target not in ("jev", "ollama"):
            raise ValueError("invalid_test_target")
        started = monotonic()
        ref = ChatRef("chat", "oc_diagnostics")
        item = AnalysisInput(VersionStamp(0, ref, "om_diagnostics", None),
                             "虚构连接测试：你好，今天过得怎么样？", ())
        count, status = 0, "ready"
        try:
            if target == "jev":
                # This gate is isolated from all real conversation permissions.
                gate = PrivacyGate()
                model = self._config["typesafe_model"]
                JevJudge(self._config["typesafe_base"], self._config["typesafe_key"], model,
                         gate, self._post).judge(item)
            else:
                count = len(ReplyGenerator(self._config["ollama_base"], self._post).generate(item, model))
        except ModelError as error:
            status = str(error) if str(error) in STATUS_LABELS else "internal_error"
        except (OSError, ValueError, TypeError):
            status = "internal_error"
        return ConnectionTest(target, model, status, monotonic() - started, count)
