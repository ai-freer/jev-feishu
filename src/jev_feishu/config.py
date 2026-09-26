"""Small, non-executable env files; secrets never copied into project config."""

import os
from pathlib import Path
import shlex
import tempfile


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
    model = app.get("JEV_FEISHU_REPLY_MODEL", "qwen3.5:4b")
    if model not in ("qwen3.5:4b", "qwen3.5:9b"):
        raise ValueError("unsupported_reply_model")
    cloud_setting = app.get("JEV_FEISHU_JEV_ENABLED", "true")
    if cloud_setting not in ("true", "false"):
        raise ValueError("invalid_jev_setting")
    return {
        "ollama_base": DEFAULT_OLLAMA,
        "reply_model": model,
        "jev_enabled": cloud_setting == "true",
        "typesafe_base": cloud.get("TYPESAFE_BASE_URL", "https://openrouter.ai/api"),
        "typesafe_model": cloud.get("TYPESAFE_DEFAULT_MODEL", "~typesafe/jev-latest"),
        "typesafe_key": cloud.get("TYPESAFE_API_KEY", ""),
    }


def save_jev_enabled(enabled: bool, path: Path = APP_CONFIG) -> None:
    if type(enabled) is not bool:
        raise ValueError("invalid_jev_setting")
    if path.is_symlink() or not path.is_file() or path.parent.stat().st_mode & 0o077:
        raise ValueError("unsafe_config_file")
    read_env(path)
    key = "JEV_FEISHU_JEV_ENABLED"
    lines = [line for line in path.read_text().splitlines()
             if line.strip().removeprefix("export ").partition("=")[0].strip() != key]
    lines.append(f"{key}={'true' if enabled else 'false'}")
    fd, temporary = tempfile.mkstemp(prefix=".jev-env-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
