"""Small, non-executable env files; secrets never copied into project config."""

import os
import hashlib
import re
from pathlib import Path
import shlex
import tempfile

from .replies import DEFAULT_TONES, migrate_tones, validate_tones
from .model_services import PROVIDERS, PROVIDER_BASES, service_endpoint, validate_base, validate_key, validate_model


APP_CONFIG = Path.home() / ".config" / "jev-feishu" / "env"
TYPESAFE_CONFIG = Path.home() / ".config" / "typesafe" / "env"
DEFAULT_OLLAMA = "http://127.0.0.1:11434/v1"


def init_app_config(path: Path = APP_CONFIG) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("unsafe_config_directory")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.stat().st_mode & 0o077:
            raise ValueError("unsafe_config_file") from None
        return
    with os.fdopen(fd, "w") as stream:
        stream.write("JEV_FEISHU_REPLY_MODEL=qwen3.5:4b\nJEV_FEISHU_JEV_ENABLED=true\n")


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise ValueError("unsafe_config_file")
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, marker, value = line.partition("=")
        if not marker or not key.isidentifier():
            raise ValueError("invalid_config_line")
        try:
            parts = shlex.split(value, comments=True)
        except ValueError:
            raise ValueError("invalid_config_line") from None
        if len(parts) > 1:
            raise ValueError("invalid_config_line")
        values[key] = parts[0] if parts else ""
    return values


def load_config(app_path: Path = APP_CONFIG, typesafe_path: Path = TYPESAFE_CONFIG):
    app = read_env(app_path)
    cloud = read_env(typesafe_path)
    model = validate_model(app.get("JEV_FEISHU_REPLY_MODEL", "qwen3.5:4b"))
    provider = app.get("JEV_FEISHU_REPLY_PROVIDER", "ollama")
    if provider not in PROVIDERS:
        raise ValueError("invalid_provider")
    reply_base = validate_base(app.get("JEV_FEISHU_REPLY_BASE_URL", PROVIDER_BASES[provider]),
                               local_only=provider == "ollama")
    shared_base = cloud.get("TYPESAFE_BASE_URL", "https://openrouter.ai/api")
    typesafe_base = validate_base(app.get("JEV_FEISHU_TYPESAFE_BASE_URL", shared_base))
    service_endpoint("jev", typesafe_base)
    # A new per-app service must not inherit another service's shared key.
    shared_key = cloud.get("TYPESAFE_API_KEY", "") if typesafe_base == shared_base.rstrip("/") else ""
    typesafe_key = validate_key(app.get("JEV_FEISHU_TYPESAFE_API_KEY", shared_key))
    cloud_setting = app.get("JEV_FEISHU_JEV_ENABLED", "true")
    if cloud_setting not in ("true", "false"):
        raise ValueError("invalid_jev_setting")
    saved_tones = app.get("JEV_FEISHU_REPLY_TONES")
    tones = migrate_tones(saved_tones.split("|") if saved_tones is not None else DEFAULT_TONES)
    return {
        "ollama_base": DEFAULT_OLLAMA,
        "reply_model": model,
        "reply_provider": provider,
        "reply_base": reply_base,
        "reply_key": validate_key(app.get("JEV_FEISHU_REPLY_API_KEY", "")),
        "reply_tones": tones,
        "jev_enabled": cloud_setting == "true",
        "typesafe_base": typesafe_base,
        "typesafe_model": validate_model(app.get("JEV_FEISHU_TYPESAFE_MODEL",
                                                cloud.get("TYPESAFE_DEFAULT_MODEL", "~typesafe/jev-latest"))),
        "typesafe_key": typesafe_key,
        "typesafe_key_source": ("本应用" if "JEV_FEISHU_TYPESAFE_API_KEY" in app else "共享 TypeSafe")
                               if typesafe_key else "未配置",
    }


def save_jev_enabled(enabled: bool, path: Path = APP_CONFIG) -> None:
    if type(enabled) is not bool:
        raise ValueError("invalid_jev_setting")
    _replace_app_setting("JEV_FEISHU_JEV_ENABLED", "true" if enabled else "false", path)


def save_reply_tones(tones, path: Path = APP_CONFIG) -> None:
    _replace_app_setting("JEV_FEISHU_REPLY_TONES", "|".join(validate_tones(tones)), path)


def _replace_app_setting(key: str, value: str, path: Path) -> None:
    write_app_settings({key: value}, path=path)


def config_revision(path: Path = APP_CONFIG) -> str:
    read_env(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_app_settings(changes: dict[str, str], *, path: Path = APP_CONFIG, expected_revision=None) -> None:
    if path.is_symlink() or not path.is_file() or path.parent.stat().st_mode & 0o077:
        raise ValueError("unsafe_config_file")
    read_env(path)
    original = path.read_text()
    if expected_revision is not None and hashlib.sha256(original.encode()).hexdigest() != expected_revision:
        raise ValueError("config_changed")
    if any(not isinstance(value, str) or any(c in value for c in "\r\n\0") for value in changes.values()):
        raise ValueError("invalid_config_value")
    remaining = dict(changes)
    lines = []
    for line in original.splitlines():
        match = re.match(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z_0-9]*)(\s*=\s*)(.*)$", line)
        if match and match[2] in changes:
            quoted, escaped, comment = None, False, ""
            for index, char in enumerate(match[4]):
                if escaped:
                    escaped = False
                elif char == "\\" and quoted != "'":
                    escaped = True
                elif quoted:
                    if char == quoted:
                        quoted = None
                elif char in "\"'":
                    quoted = char
                elif char == "#":
                    comment = " " + match[4][index:]
                    break
            line = f"{match[1]}{match[2]}{match[3]}{shlex.quote(changes[match[2]])}{comment}"
            remaining.pop(match[2], None)
        lines.append(line)
    lines.extend(f"{key}={shlex.quote(value)}" for key, value in remaining.items())
    fd, temporary = tempfile.mkstemp(prefix=".jev-env-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or path.read_text() != original:
            raise ValueError("config_changed")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
