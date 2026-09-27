"""Explicit provider routing. No discovery traffic or fallback at import time."""

import ipaddress
import re
from urllib.parse import urlencode, urlsplit

from .http_client import ModelError, get_json


PROVIDERS = {"ollama": "本机 Ollama", "openai": "OpenAI 兼容", "anthropic": "Anthropic 兼容"}
PROVIDER_BASES = {"ollama": "http://127.0.0.1:11434/v1", "openai": "https://api.openai.com/v1",
                  "anthropic": "https://api.anthropic.com"}


def is_loopback(base: str) -> bool:
    host = urlsplit(base).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def validate_base(base: str, *, local_only=False) -> str:
    if not isinstance(base, str):
        raise ValueError("invalid_service_url")
    value = base.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError("invalid_service_url") from None
    if (not value or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value)
            or "\\" in value or parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None or "?" in value or "#" in value
            or (port is not None and not 1 <= port <= 65535)
            or (parts.scheme == "http" and not is_loopback(value))
            or (local_only and not is_loopback(value))):
        raise ValueError("invalid_service_url")
    return value


def validate_model(model: str) -> str:
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError("invalid_model_name")
    value = model.strip()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid_model_name")
    return value


def validate_key(key: str) -> str:
    if not isinstance(key, str) or any(not 33 <= ord(c) <= 126 for c in key):
        raise ValueError("invalid_api_key")
    return key


def service_endpoint(provider: str, base: str) -> str:
    if provider not in (*PROVIDERS, "jev"):
        raise ValueError("invalid_provider")
    value = validate_base(base, local_only=provider == "ollama")
    if provider == "jev" and urlsplit(value).scheme != "https":
        raise ValueError("invalid_service_url")
    actions = ("/systemone", "/evaluate", "/decisions") if provider == "jev" else (
        ("/messages",) if provider == "anthropic" else ("/chat/completions",))
    if value.endswith(actions):
        return value
    if not re.fullmatch(r"v\d+(?:[a-z][a-z0-9]*)?", urlsplit(value).path.rsplit("/", 1)[-1]):
        value += "/v1"
    return value + actions[0]


def auth_headers(provider: str, key: str) -> dict[str, str]:
    validate_key(key)
    if provider == "anthropic":
        return {"anthropic-version": "2023-06-01", **({"x-api-key": key} if key else {})}
    if key or provider == "ollama":
        return {"authorization": f"Bearer {key or 'ollama'}"}
    return {}


def reply_options(config) -> dict:
    return {"base": config.get("reply_base", config.get("ollama_base", PROVIDER_BASES["ollama"])),
            "provider": config.get("reply_provider", "ollama"), "key": config.get("reply_key", "")}


def model_list(provider: str, base: str, key: str, *, get=get_json) -> tuple[str, ...]:
    endpoint = service_endpoint(provider, base)
    if provider == "jev" and endpoint.endswith(("/evaluate", "/decisions")):
        raise ModelError("models_unavailable")
    action = "/systemone" if provider == "jev" else "/messages" if provider == "anthropic" else "/chat/completions"
    url = endpoint.removesuffix(action) + "/models"
    headers = auth_headers(provider, key)
    offered, seen_pages = [], set()
    for _ in range(5):
        data = get(url, 10, headers=headers)
        native = provider == "jev" and "models" in data
        entries = data.get("models" if native else "data")
        if not isinstance(entries, list):
            raise ModelError("invalid_response")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ModelError("invalid_response")
            try:
                model = validate_model(entry.get("name" if native else "id"))
            except ValueError:
                raise ModelError("invalid_response") from None
            if (provider == "jev" and urlsplit(base).hostname == "openrouter.ai"
                    and not model.startswith(("typesafe/", "~typesafe/"))):
                continue
            if model not in offered:
                offered.append(model)
        if not data.get("has_more"):
            return tuple(offered)
        last = data.get("last_id")
        if provider != "anthropic" or not isinstance(last, str) or not last or last in seen_pages:
            raise ModelError("models_incomplete")
        seen_pages.add(last)
        url = endpoint.removesuffix(action) + "/models?" + urlencode({"after_id": last})
    raise ModelError("models_incomplete")
