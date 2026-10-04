#!/usr/bin/env bash
#
# Builds the macOS bridge as a real .app bundle.
#
# Hand-assembled rather than produced by xcodebuild, because this project must
# build on a machine with only the Command Line Tools installed. An .app bundle
# is a directory with a known layout and an Info.plist; nothing about it needs
# Xcode. What Xcode would add — a project file and a code-signing step — is
# replaced by this script and by an explicit `codesign` call at the end.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${CONFIG:-release}"
APP_NAME="Figma Fusion Bridge"
BUNDLE_ID="com.figmafusionbridge.helper"
VERSION="$(grep -m1 'static let version' "$ROOT/bridge-macos/Sources/BridgeCore/BridgeServer.swift" | sed 's/.*"\(.*\)".*/\1/')"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"

echo "==> Building FigmaFusionBridge ($CONFIG, arm64) v$VERSION"
cd "$ROOT/bridge-macos"
swift build -c "$CONFIG" --arch arm64 2>&1

BIN="$(swift build -c "$CONFIG" --arch arm64 --show-bin-path)/FigmaFusionBridge"
if [[ ! -x "$BIN" ]]; then
  echo "error: build produced no binary at $BIN" >&2
  exit 1
fi

echo "==> Assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/FigmaFusionBridge"

# The Resolve-side payload travels inside the bundle so the in-app installer has
# something to copy. Keeping it here rather than downloading it later is what
# makes the whole product work offline.
cp -R "$ROOT/resolve/ffbridge" "$APP/Contents/Resources/ffbridge"
cp "$ROOT/resolve/lua/ffbridge.lua" "$APP/Contents/Resources/ffbridge.lua"
cp "$ROOT/resolve/ffbridge_launcher.py" "$APP/Contents/Resources/ffbridge_launcher.py"
cp -R "$ROOT/resolve/scripts" "$APP/Contents/Resources/scripts"
find "$APP/Contents/Resources" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key><string>FigmaFusionBridge</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <!-- A menu-bar utility: no Dock icon, no default window. -->
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSHumanReadableCopyright</key><string>MIT licensed.</string>
    <!-- Stated explicitly so the value is auditable: the server binds 127.0.0.1
         only, and there is no code path that binds any other interface. -->
    <key>NSLocalNetworkUsageDescription</key>
    <string>Figma Fusion Bridge listens only on this Mac (127.0.0.1) so the Figma plugin and DaVinci Resolve can talk to each other. Nothing is sent over the network.</string>
</dict>
</plist>
PLIST

printf 'APPL????' > "$APP/Contents/PkgInfo"

echo "==> Signing"
# Ad-hoc signature. Enough for the app to run and for the local network prompt
# to name it correctly; replace the identity for distribution.
codesign --force --deep --sign - --timestamp=none "$APP" 2>&1 | sed 's/^/    /' || {
  echo "    warning: ad-hoc signing failed; the app will still run locally" >&2
}

echo "==> Verifying"
ARCHS="$(lipo -archs "$APP/Contents/MacOS/FigmaFusionBridge" 2>/dev/null || echo unknown)"
echo "    architectures: $ARCHS"
if [[ "$ARCHS" != *arm64* ]]; then
  echo "error: binary is not arm64" >&2
  exit 1
fi
if [[ "$ARCHS" == *x86_64* ]]; then
  echo "    note: universal binary; Apple Silicon runs the arm64 slice natively"
fi
codesign --verify --verbose=1 "$APP" 2>&1 | sed 's/^/    /' || true

SIZE="$(du -sh "$APP" | cut -f1)"
echo
echo "Built $APP ($SIZE)"
echo "Run it with: open \"$APP\""
