#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
uv sync --python 3.12 --no-dev --quiet

build_root="$(mktemp -d -t jev-feishu-build)"
trap 'rm -rf "$build_root"' EXIT
output_app="$PWD/dist/build.noindex/Jev 飞书助手.app"
app_path="$build_root/Jev 飞书助手.app"
runtime_source="$(uv run --python 3.12 python -c 'import sys; print(sys.base_prefix)')"
runtime_target="$app_path/Contents"
site_target="$runtime_target/lib/python3.12/site-packages"

mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources" "$site_target"
cp LICENSE "$app_path/Contents/Resources/LICENSE"
cp packaging/assets/JevFeishu.icns "$app_path/Contents/Resources/JevFeishu.icns"
cp "$runtime_source/bin/python3.12" "$app_path/Contents/MacOS/JevFeishuPython"
rsync -a --exclude='__pycache__' --exclude='*.pyc' "$runtime_source/lib/" "$runtime_target/lib/"
rsync -a --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='__editable__*.pth' --exclude='jev_feishu-*.dist-info' \
  .venv/lib/python3.12/site-packages/ "$site_target/"
rsync -a --exclude='__pycache__' --exclude='*.pyc' src/jev_feishu/ "$site_target/jev_feishu/"

cat > "$site_target/sitecustomize.py" <<'PYTHON'
import sys

if sys.argv == [""]:
    from jev_feishu.app import main
    main()
PYTHON

cat > "$app_path/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Jev 飞书助手</string>
  <key>CFBundleDisplayName</key><string>Jev 飞书助手</string>
  <key>CFBundleExecutable</key><string>JevFeishu</string>
  <key>CFBundleIdentifier</key><string>com.danielpan.jevfeishu</string>
  <key>CFBundleIconFile</key><string>JevFeishu.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

sdk_root="${SDKROOT:-/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk}"
if [[ ! -d "$sdk_root" ]]; then
  sdk_root=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
fi
SDKROOT="$sdk_root" rustc --edition 2021 -C linker=rust-lld packaging/launcher.rs \
  -o "$app_path/Contents/MacOS/JevFeishu"

"$app_path/Contents/MacOS/JevFeishuPython" -B -c \
  'import AppKit, ApplicationServices, jev_feishu.app, sys; assert sys.prefix.endswith("/Contents")'
plutil -lint "$app_path/Contents/Info.plist"
xattr -rc "$app_path"
signing_identity="${JEV_FEISHU_SIGN_IDENTITY:-}"
if [[ -z "$signing_identity" ]]; then
  development_identities="$(security find-identity -v -p codesigning \
    | awk '/"Apple Development:/ { print $2 }')"
  if [[ -z "$development_identities" ]]; then
    signing_identity="-"
  elif [[ "$development_identities" == *$'\n'* ]]; then
    echo "Multiple Apple Development identities; set JEV_FEISHU_SIGN_IDENTITY." >&2
    exit 1
  else
    signing_identity="$development_identities"
  fi
fi
codesign --force --deep --sign "$signing_identity" "$app_path"
xattr -rc "$app_path"
codesign --verify --deep --strict "$app_path"

# Managed output directories can reacquire FinderInfo after cleanup. Check the
# published bytes in a clean copy, as the /Applications installer does.
verification_app="$build_root/published/Jev 飞书助手.app"
mkdir -p "$output_app" "$verification_app"
rsync -a --delete "$app_path/" "$output_app/"
rsync -a "$output_app/" "$verification_app/"
codesign --verify --deep --strict "$verification_app"
