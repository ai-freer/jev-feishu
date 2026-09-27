"""Model form drafts and safe persistence; saving never switches live clients."""

from .config import APP_CONFIG, TYPESAFE_CONFIG, config_revision, load_config, read_env, write_app_settings
from .diagnostics import Diagnostics
from .model_services import model_list, service_endpoint, validate_base, validate_key, validate_model


FORM_KEYS = {
    "reply_provider": "JEV_FEISHU_REPLY_PROVIDER", "reply_base": "JEV_FEISHU_REPLY_BASE_URL",
    "reply_model": "JEV_FEISHU_REPLY_MODEL", "typesafe_base": "JEV_FEISHU_TYPESAFE_BASE_URL",
    "typesafe_model": "JEV_FEISHU_TYPESAFE_MODEL",
}
KEY_FIELDS = {"reply": "JEV_FEISHU_REPLY_API_KEY", "jev": "JEV_FEISHU_TYPESAFE_API_KEY"}
SETTINGS_ERRORS = {
    "config_changed": "配置已被其他操作修改。请关闭设置后重新打开，再编辑。",
    "invalid_service_url": "服务地址无效：远端须用 HTTPS，不含用户名、密码、查询参数；Ollama 仅限本机。",
    "invalid_model_name": "请填写模型 ID，不可含空白或控制字符。",
    "invalid_provider": "请选择受支持的回复接口。",
    "invalid_api_key": "密钥含空格或非法字符，请重新粘贴。",
    "new_service_key_required": "更换服务地址或接口时，请填写新服务的密钥，或明确勾选清除密钥。",
    "models_unavailable": "完整 Jev 动作地址无法推导模型列表，请手动填写模型 ID。",
    "models_incomplete": "服务返回的模型列表不完整，请手动填写模型 ID。",
    "not_configured": "尚未配置此服务的密钥。",
    "unauthorized": "服务认证失败，请检查密钥与服务地址。",
    "rate_limited": "服务请求受限，请稍后再试。",
    "connection_error": "连接失败或超时，请检查地址和网络。",
    "http_error": "服务返回错误，请检查地址、模型和接口类型。",
    "invalid_response": "服务响应格式不符，请检查接口类型。",
    "thinking_only": "模型只返回思考内容，请换用可输出回复文本的模型。",
    "insufficient_candidates": "模型未返回两条候选，请重试或更换模型。",
}


def settings_error(error) -> str:
    return SETTINGS_ERRORS.get(str(error), "操作未完成，请检查配置文件权限和服务状态。")


class ModelSettingsEditor:
    def __init__(self, path=APP_CONFIG, shared_path=TYPESAFE_CONFIG):
        self.path = path
        self.shared_path = shared_path
        self.revision = config_revision(path)
        self.config = load_config(path, shared_path)
        self._app_values = read_env(path)
        self.assert_unmodified()

    def assert_unmodified(self):
        if config_revision(self.path) != self.revision:
            raise ValueError("config_changed")

    def public_values(self):
        return {key: self.config[key] for key in FORM_KEYS}

    def key_note(self, target):
        if target == "jev":
            return self.config["typesafe_key_source"]
        return "本应用" if self.config["reply_key"] else "未配置"

    def preview(self, values, *, keys=None, clear=(), target=None, require_model=True):
        if set(values) != set(FORM_KEYS) or not set(clear) <= set(KEY_FIELDS):
            raise ValueError("invalid_config_value")
        candidate = dict(self.config)
        keys = keys or {}
        if not set(keys) <= set(KEY_FIELDS):
            raise ValueError("invalid_config_value")
        changes = {}
        for section in ((target,) if target else ("jev", "reply")):
            if section not in KEY_FIELDS:
                raise ValueError("invalid_provider")
            prefix = "typesafe" if section == "jev" else "reply"
            provider = "jev" if section == "jev" else values["reply_provider"]
            base = validate_base(values[prefix + "_base"], local_only=provider == "ollama")
            service_endpoint(provider, base)
            model = validate_model(values[prefix + "_model"]) if require_model else values[prefix + "_model"].strip()
            candidate[prefix + "_base"], candidate[prefix + "_model"] = base, model
            if (base != self.config[prefix + "_base"] or
                    (section == "reply" and provider != self.config["reply_provider"])):
                changes[FORM_KEYS[prefix + "_base"]] = base
            if model != self.config[prefix + "_model"]:
                changes[FORM_KEYS[prefix + "_model"]] = model
            if section == "reply":
                candidate["reply_provider"] = provider
                if provider != self.config["reply_provider"]:
                    changes[FORM_KEYS["reply_provider"]] = provider
            supplied = keys.get(section)
            moved = (base != self.config[prefix + "_base"] or
                     (section == "reply" and provider != self.config["reply_provider"]))
            if section in clear and supplied:
                raise ValueError("invalid_api_key")
            if supplied:
                candidate[prefix + "_key"] = validate_key(supplied)
                changes[KEY_FIELDS[section]] = supplied
            elif section in clear:
                candidate[prefix + "_key"] = ""
                changes[KEY_FIELDS[section]] = ""
            elif moved:
                if self.config[prefix + "_key"]:
                    raise ValueError("new_service_key_required")
                candidate[prefix + "_key"] = ""
                # Prevent load_config from importing a shared key for a new address.
                changes[KEY_FIELDS[section]] = ""
        return candidate, changes

    def save(self, values, *, keys=None, clear=()):
        self.assert_unmodified()
        candidate, changes = self.preview(values, keys=keys, clear=clear)
        if changes:
            write_app_settings(changes, path=self.path, expected_revision=self.revision)
        self.__init__(self.path, self.shared_path)
        return self.public_values()

    def after_global_toggle(self):
        # Only rebase our own single-field live toggle, never unrelated edits.
        values = read_env(self.path)
        def without_toggle(data):
            return {key: value for key, value in data.items() if key != "JEV_FEISHU_JEV_ENABLED"}
        if without_toggle(values) != without_toggle(self._app_values):
            raise ValueError("config_changed")
        self.revision = config_revision(self.path)
        self._app_values = values

    def list_models(self, target, values, *, keys=None, clear=()):
        candidate, _ = self.preview(values, keys=keys, clear=clear, target=target, require_model=False)
        prefix = "typesafe" if target == "jev" else "reply"
        provider = "jev" if target == "jev" else candidate["reply_provider"]
        return model_list(provider, candidate[prefix + "_base"], candidate[prefix + "_key"])

    def test(self, target, values, *, keys=None, clear=()):
        candidate, _ = self.preview(values, keys=keys, clear=clear, target=target)
        return Diagnostics(candidate).test_connection("jev" if target == "jev" else "ollama",
                                                      candidate["reply_model"])
