#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source_app="$PWD/dist/Jev 飞书助手.app"
target_app="/Applications/Jev 飞书助手.app"

if [[ ! -d "$source_app" ]]; then
  echo "Build the app first: packaging/build_app.sh" >&2
  exit 1
fi
if pgrep -f "$target_app/Contents/MacOS/JevFeishu$" >/dev/null; then
  echo "Quit the installed Jev 飞书助手 before updating it." >&2
  exit 1
fi

rsync -a --delete "$source_app/" "$target_app/"
xattr -rc "$target_app"
codesign --verify --deep --strict "$target_app"
printf '%s\n' "$target_app"
