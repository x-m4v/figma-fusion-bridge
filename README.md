# Figma Fusion Bridge

[Русский](README.ru.md) · [Installation](#installation) · [Validation](docs/VALIDATION.md) · [Publishing](docs/PUBLISHING.ru.md)

An independent, experimental local bridge from a Figma selection to an editable
Fusion composition in DaVinci Resolve. MIT licensed.

It consists of **three parts**: a Figma development plugin, a local bridge app,
and Lua menu commands backed by a Python graph builder. The bridge runs on the
same computer as Figma and Resolve. Design transfer uses loopback HTTP, a pairing
code, and an authentication token; it does not use a remote transfer service.

## Status and requirements

| Platform | Status | Requirements |
|---|---|---|
| macOS | App builds; automated checks pass. Full Figma → Resolve acceptance remains pending. | macOS 14+, Apple Silicon, Python 3.9+ |
| Windows | Windows app, installer and native CI build are provided. See Actions/VALIDATION for actual run results. | Windows 10/11, x64; release bundles Python |

Use **Figma desktop** to import the development plugin. A browser alone is not
the supported installation route. Resolve must support the Lua menu commands and
nodes used by this project. Free/Studio and individual Resolve releases need
separate acceptance testing; compatibility is not guaranteed solely by unit tests.

## Installation

Download the archive for your OS from this repository's **Releases**, when a
release has been created. GitHub's **Code → Download ZIP** downloads source code
and does not include built apps. Development builds are also available under
**Actions → Check and build → Artifacts** after a successful run.

### macOS

1. Extract the macOS ARM64 archive into a permanent folder.
2. Install Python 3.9+ if `python3` is not available. Node.js and Swift are not needed for a release package.
3. Run `Install.command`; it installs scripts for your user and opens the app. Alternatively, use `python3 bridge-python/app.py --install` from the extracted folder, then open the app.
4. Restart Resolve. Keep the bridge app running in the menu bar.

The app is ad-hoc signed, **not Apple-notarized**. A downloaded copy may be blocked
by Gatekeeper. If you trust the source, use the macOS Privacy & Security approval
flow; do not disable Gatekeeper system-wide. Public distribution without this
warning requires Developer ID signing and notarization.

### Windows

1. Extract the Windows x64 archive into a permanent folder. Keep the whole
   `FigmaFusionBridge` directory, including `_internal`, together.
2. Double-click `Install.cmd`, or open `FigmaFusionBridge/FigmaFusionBridge.exe`
   and click **Install / repair Resolve scripts**. No administrator rights are needed.
3. Restart Resolve. Keep the bridge window open. Enter its pairing code in Figma.

The Windows executable is unsigned. Do not disable antivirus to run it. Moving
the app after installation requires running the installer again. Spaces and Unicode in paths are supported. The Windows launcher uses LuaJIT and
Unicode process APIs instead of shell expansion.

### Figma and first import — both platforms

1. In Figma desktop: **Plugins → Development → Import plugin from manifest**.
2. Select `figma-plugin/manifest.json` from the extracted release.
3. Run the plugin and enter the pairing code from the bridge app.
4. Start with a plain, solid-filled rectangle **without a stroke**. Select it and
   click **Send to Fusion**.
5. Open a test composition on Resolve's Fusion page. Use
   **Workspace → Scripts → Figma Fusion Bridge - Connection Test**, then
   **Figma Fusion Bridge - Receive**.
6. Inspect the resulting nodes and rendered output before using it in production.

## Current limitations

- Receive inserts a **new graph** each time. Existing animation is not updated or
  preserved automatically. Re-sync planning code exists, but this Lua path does not apply it.
- **Pull Figma Selection is not implemented** by the bridge; use Send to Fusion.
- Live Sync in the Figma plugin updates the transfer available to Receive; it does
  not automatically update an open Resolve composition.
- The Receive compatibility pass uses masks for solid rectangles and ellipses.
  Branches requiring experimental `sRender` support, including some strokes and
  polygons, are blocked. The older pricing-card example is an offline builder
  example and may be blocked by Receive. Use `examples/starter-transfer.json`
  for the HTTP/CLI smoke test.
- Blur, blend modes, corner smoothing and typography can differ. Color management
  must be checked visually on the actual Resolve installation. Font files are not
  transferred or bundled; install the required fonts separately with permission.
- Automated tests do not prove visual fidelity or native Resolve renderer stability.

## Building from source

Prerequisites: Node.js 24, Python 3.9+ on macOS / 3.11 on Windows. The native macOS
app also requires Xcode Command Line Tools. Windows binaries are built on Windows.

```sh
npm ci
npm run build
npm run typecheck
python3 -m pip install -r requirements-dev.txt
python3 -m pytest resolve/tests bridge-python/tests -q
```

On Windows use `python` instead of `python3` for test commands. To install from source:

```sh
# macOS
bash scripts/install.sh
```

```powershell
# Windows, in a normal PowerShell prompt; review the script before running it
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-windows.ps1
```

The source plugin manifest is `packages/figma-plugin/manifest.json`.
For Windows packaging, install `requirements-build.txt` and run
`scripts/build-windows.ps1`. CI builds both platforms, tests the Windows executable,
and uploads ZIP artifacts. See [validation](docs/VALIDATION.md).

## Data and uninstall

macOS data: `~/Library/Application Support/FigmaFusionBridge`.
Windows data: `%LOCALAPPDATA%/FigmaFusionBridge`.
Windows menu scripts: `%APPDATA%/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts`.

Remove only the three `Figma Fusion Bridge - *.lua` menu commands from `Comp` and
`Utility` to uninstall, then remove the app. **Keep Assets, BridgeAssets and other
project data** while any Fusion composition refers to imported image paths.
Never upload `session.json`, `credentials.json`, local caches or real design exports.

## License and independence

Original code is covered by [MIT](LICENSE); dependency terms are in
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) and `licenses/`.
This is not an official Figma or Blackmagic Design product. No vendor SDK binaries,
fonts or third-party design files are distributed. See the scoped
[publication review](docs/OPEN_SOURCE_REVIEW.ru.md); it is not a guarantee about the
provenance of every original line of code.
