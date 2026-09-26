"""Find an existing lark-cli from a Finder-launched app without changing auth state."""

from pathlib import Path
import os
import shutil


def lark_cli_path() -> str:
    direct = shutil.which("lark-cli")
    if direct:
        return direct
    candidates = [
        Path.home() / ".local" / "bin" / "lark-cli",
        Path("/opt/homebrew/bin/lark-cli"),
        Path("/usr/local/bin/lark-cli"),
    ]
    node_root = Path.home() / ".nvm" / "versions" / "node"
    if node_root.is_dir():
        candidates.extend(sorted(node_root.glob("*/bin/lark-cli"), reverse=True))
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return str(candidate)
    raise FileNotFoundError("lark_cli_unavailable")


def lark_cli_env(binary: str) -> dict[str, str]:
    # Keep the launcher directory: resolving the npm symlink loses its sibling node.
    directory = str(Path(binary).absolute().parent)
    return {**os.environ,
            "PATH": directory + os.pathsep + os.environ.get("PATH", os.defpath),
            "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
            "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"}
