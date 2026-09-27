"""TypeSafe Jev judgement, gated globally before any request."""

from dataclasses import dataclass

from .http_client import ModelError, post_json
from .model_services import service_endpoint, validate_key, validate_model
from .privacy import PrivacyGate
from .session import AnalysisInput


INTENTS = {
    "派活": "对方要我做一件事或接一个任务",
    "催进度": "对方在催促我尽快完成某个已在办的事",
    "问进度": "对方在询问某件事的进展或状态",
    "批评": "对方对我的工作或结果表达不满、指出错误",
    "要解释": "对方要求我说明原因或给出解释",
    "闲聊": "对方只是在聊天、分享或表达感受，没有具体要求",
    "约会议": "对方想安排一次会议或通话",
    "夸奖": "对方在肯定、称赞我的成果",
}
RISK_LEVELS = (
    "完全没风险，怎么回都行", "基本没风险", "平淡，正常回就好", "需要稍微留神",
    "有点敏感，措辞注意", "需要谨慎，可能被挑刺", "比较危险，容易得罪人或踩坑",
    "很危险，说错要出问题", "非常危险，涉及责任或利益", "极度危险，先别回，想清楚再说",
)


@dataclass(frozen=True, repr=False)
class Verdict:
    intent: str
    confidence: float
    risk: float


def endpoint(base: str) -> str:
    return service_endpoint("jev", base)


class JevJudge:
    def __init__(self, base: str, key: str, model: str, gate: PrivacyGate,
                 transport=post_json):
        self._url = endpoint(base)
        self._key = validate_key(key)
        self._model = validate_model(model)
        self._gate = gate
        self._transport = transport

    def judge(self, item: AnalysisInput) -> Verdict | None:
        if not self._gate.allows_cloud():
            return None
        if not self._key:
            raise ModelError("not_configured")
        state = "\n\n".join((*reversed(item.context), item.text))
        payload = {
            "model": self._model,
            "state": state,
            "questions": {
                "intent": {"type": "choice", "instructions": "这句话的真实意图是什么？", "criteria": INTENTS},
                "risk": {"type": "score", "instructions": "如果直接回复这句话，风险有多大？", "criteria": list(RISK_LEVELS)},
            },
        }
        data = self._transport(self._url, {"content-type": "application/json",
                      "authorization": f"Bearer {self._key}"}, payload, 15)
        try:
            answers = data["answers"]
            intent = answers["intent"]["choice"]
            confidence = float(answers["intent"]["confidence"])
            risk = float(answers["risk"]["score"])
            if intent not in INTENTS or not 0 <= confidence <= 1 or not 0 <= risk <= 9:
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ModelError("invalid_response") from None
        return Verdict(intent, confidence, risk)
