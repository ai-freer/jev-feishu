#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -m)" == "arm64" ]] || { echo "This release supports Apple Silicon only." >&2; exit 1; }
version="$(awk -F '"' '/^__version__ =/ {print $2}' src/jev_feishu/__init__.py)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
# Public artifacts must not embed a developer's personal signing certificate.
JEV_FEISHU_SIGN_IDENTITY=- bash packaging/build_app.sh
staging="$(mktemp -d -t jev-feishu-release)"
trap 'rm -rf "$staging"' EXIT
app="$staging/Jev 飞书助手.app"
rsync -a "dist/build.noindex/Jev 飞书助手.app/" "$app/"
xattr -rc "$app"
codesign --verify --deep --strict "$app"
ln -s /Applications "$staging/Applications"
cp packaging/INSTALL.zh-CN.md "$staging/安装说明.md"
cp LICENSE "$staging/LICENSE"
mkdir -p dist/releases.noindex
filename="Jev-Feishu-${version}-macOS-arm64.dmg"
hdiutil create -volname "Jev Feishu $version" -srcfolder "$staging" -format UDZO \
  -ov "dist/releases.noindex/$filename"
(cd dist/releases.noindex && shasum -a 256 "$filename" > "$filename.sha256")
