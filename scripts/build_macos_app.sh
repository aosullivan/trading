#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  python3 -m venv "$ROOT_DIR/venv"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt"

ICON_SRC="$ROOT_DIR/static/favicon.svg"
ICON_BUILD_DIR="$ROOT_DIR/build/icon"
ICONSET_DIR="$ICON_BUILD_DIR/TriedingView.iconset"
ICON_PNG="$ICON_BUILD_DIR/favicon.svg.png"
ICON_ICNS="$ICON_BUILD_DIR/TriedingView.icns"

rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"
qlmanage -t -s 1024 -o "$ICON_BUILD_DIR" "$ICON_SRC" >/dev/null 2>&1

for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" "$ICON_PNG" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
done

cp "$ICONSET_DIR/icon_32x32.png" "$ICONSET_DIR/icon_16x16@2x.png"
cp "$ICONSET_DIR/icon_64x64.png" "$ICONSET_DIR/icon_32x32@2x.png"
cp "$ICONSET_DIR/icon_256x256.png" "$ICONSET_DIR/icon_128x128@2x.png"
cp "$ICONSET_DIR/icon_512x512.png" "$ICONSET_DIR/icon_256x256@2x.png"
sips -z 1024 1024 "$ICON_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"

"$VENV_PYTHON" -m PyInstaller \
  --name TriedingView \
  --windowed \
  --noconfirm \
  --clean \
  --icon "$ICON_ICNS" \
  --add-data "$ROOT_DIR/watchlist.json:." \
  --add-data "$ROOT_DIR/templates:templates" \
  --add-data "$ROOT_DIR/static:static" \
  "$ROOT_DIR/desktop_app.py"
