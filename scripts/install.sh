#!/usr/bin/env bash
#
# One-command setup: build everything, install the Resolve payload, and say
# what is left for the user to do by hand.
#
# The Figma plugin is the one step that cannot be automated — Figma does not
# allow programmatic plugin installation — so this script ends by printing the
# exact path to import.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/FigmaFusionBridge"
RESOLVE_SCRIPTS="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }

say "Checking this machine"

[[ "$(uname -s)" == "Darwin" ]] || die "This tool is macOS only."
if [[ "$(uname -m)" != "arm64" ]]; then
  warn "Not Apple Silicon. The build targets arm64; expect trouble."
else
  ok "macOS $(sw_vers -productVersion) on Apple Silicon"
fi

command -v swift >/dev/null || die "Swift not found. Install the Xcode Command Line Tools: xcode-select --install"
ok "Swift $(swift --version 2>&1 | head -1 | sed 's/.*version \([0-9.]*\).*/\1/')"

command -v node >/dev/null || die "Node.js not found. Install Node 20 or later."
ok "Node $(node --version)"

command -v python3 >/dev/null || die "Python 3 not found."
ok "Python $(python3 --version | cut -d' ' -f2)"

RESOLVE_APP=""
for candidate in "/Applications/DaVinci Resolve/DaVinci Resolve.app" "/Applications/DaVinci Resolve.app"; do
  [[ -d "$candidate" ]] && RESOLVE_APP="$candidate" && break
done
if [[ -n "$RESOLVE_APP" ]]; then
  RESOLVE_VER="$(defaults read "$RESOLVE_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo '?')"
  ok "DaVinci Resolve $RESOLVE_VER"
else
  warn "DaVinci Resolve not found. The scripts will be installed anyway."
fi

say "Building"
cd "$ROOT"
npm ci --no-audit --no-fund
ok "dependencies"
npx tsc -p packages/schema/tsconfig.json
ok "interchange schema"
( cd packages/figma-plugin && node build.mjs >/dev/null )
ok "Figma plugin bundle"
CONFIG=release bash scripts/build-app.sh >/dev/null
ok "macOS bridge (dist/Figma Fusion Bridge.app)"

say "Installing the Resolve payload"
mkdir -p "$SUPPORT/lib" "$RESOLVE_SCRIPTS"
rm -rf "$SUPPORT/lib/ffbridge"
cp -R "$ROOT/resolve/ffbridge" "$SUPPORT/lib/ffbridge"
find "$SUPPORT/lib" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
ok "bridge library → $SUPPORT/lib/ffbridge"

# Clear layouts left by earlier versions. Resolve lists only files sitting
# directly in these folders — it does not descend into subdirectories — and it
# only lists .py files when a Python framework happens to be installed in a
# system location, which is why the menu commands are Lua.
rm -rf "$RESOLVE_SCRIPTS/Comp/Figma Fusion Bridge" "$RESOLVE_SCRIPTS/Utility/Figma Fusion Bridge"
rm -f "$RESOLVE_SCRIPTS/Comp/Figma Fusion Bridge - "*.py \
      "$RESOLVE_SCRIPTS/Utility/Figma Fusion Bridge - "*.py \
      "$RESOLVE_SCRIPTS/_bootstrap.py"
cp -R "$ROOT/resolve/scripts/." "$RESOLVE_SCRIPTS/"
ok "menu commands → Fusion/Scripts"

cp "$ROOT/resolve/lua/ffbridge.lua" "$SUPPORT/lib/ffbridge.lua"
cp "$ROOT/resolve/ffbridge_launcher.py" "$SUPPORT/lib/ffbridge_launcher.py"
printf '%s\n' "$(command -v python3)" > "$SUPPORT/lib/python-path.txt"
ok "Lua helper → $SUPPORT/lib"

say "Verifying"
python3 - <<PY
import sys
sys.path.insert(0, "$SUPPORT/lib")
from ffbridge.builder import build_graph  # noqa: F401
from ffbridge.cli import main  # noqa: F401
from ffbridge import __version__
print(f"  \033[32m✓\033[0m bridge library imports (v{__version__})")
PY
[[ -f "$RESOLVE_SCRIPTS/Comp/Figma Fusion Bridge - Receive.lua" ]] \
  && ok "menu commands in place" || die "script install failed"
[[ -f "$SUPPORT/lib/ffbridge.lua" ]] \
  && ok "Lua helper in place" || die "Lua helper install failed"

say "Two steps left, by hand"
cat <<TXT

  1. Open the bridge:
       open "$ROOT/dist/Figma Fusion Bridge.app"

  2. In Figma: Plugins → Development → Import plugin from manifest…
       $ROOT/packages/figma-plugin/manifest.json

     Then run the plugin and enter the pairing code from the app's Status tab.

TXT

if pgrep -x "Resolve" >/dev/null 2>&1; then
  printf '  \033[33m!\033[0m DaVinci Resolve is running. Restart it — it scans its\n'
  printf '    Scripts folder only at startup.\n\n'
fi
