> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Installation

Three pieces install separately: the macOS app, the Resolve scripts (installed
by the app), and the Figma plugin.

## Requirements

| | |
|---|---|
| macOS | 14 or later |
| Mac | Apple Silicon (M1 or newer). Native arm64, no Rosetta |
| DaVinci Resolve | 21. Verified against 21.0.3, Free and Studio |
| Figma | Desktop app or browser |

To build from source you also need Node.js 20+ and Swift 5.9+. A full Xcode
install is **not** required — the Command Line Tools are enough.

## 1. Build

```bash
npm install
make build
```

That produces `dist/Figma Fusion Bridge.app`, the compiled schema, and the
plugin bundle in `packages/figma-plugin/dist/`.

Move the app to `/Applications` if you want it out of the build folder.

## 2. Start the bridge

Open the app. It has no Dock icon by design — look for the branch icon in the
menu bar.

Confirm it is listening:

```bash
curl http://127.0.0.1:8787/api/hello
```

```json
{"app":"figma-fusion-bridge","schemaVersion":"1.0.0","paired":false,"version":"0.1.0"}
```

## 3. Install the Resolve scripts

In the app: **Setup ▸ Install scripts**.

They go to your own Application Support folder, so no administrator password is
needed:

```
~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/
├── Comp/Figma Fusion Bridge/
│   ├── Receive.py
│   ├── Receive Into Current Composition.py
│   └── Pull Current Figma Selection.py
└── Utility/Figma Fusion Bridge/
    └── Connection Test.py
```

> **Restart DaVinci Resolve if it was already running.** Resolve scans its
> Scripts folder once, at startup. This is the single most common reason the
> menu entries do not appear.

Verify from inside Resolve:
**Workspace → Scripts → Figma Fusion Bridge - Connection Test**.
It prints what it found and what it could not reach.

## 4. Install the Figma plugin

Figma does not allow programmatic plugin installation, so this step is manual —
once.

1. In Figma: **Plugins ▸ Development ▸ Import plugin from manifest…**
2. Choose `packages/figma-plugin/manifest.json`.
3. The plugin appears under **Plugins ▸ Development ▸ Figma Fusion Bridge**.

## 5. Pair

1. Run the plugin in Figma.
2. It shows a pairing field.
3. In the bridge app, open **Status** and read the six-character code.
4. Type it into the plugin and press **Connect**.

The plugin stores the resulting token, so this is a one-time step. The code
expires after ten minutes and changes on every launch of the app — that is
deliberate: a loopback port is reachable from any web page you have open, so the
port alone is not a permission.

## 6. First transfer

1. Select a frame in Figma.
2. Press **Send to Fusion**.
3. In Resolve, open a clip on the Fusion page.
4. **Workspace → Scripts → Figma Fusion Bridge - Receive**.

The Console prints a transfer log: node count, asset count, timing, and any
warnings by layer name.

## Where things live

| | |
|---|---|
| Assets | `~/Library/Application Support/FigmaFusionBridge/Assets` |
| Transfers | `~/Library/Application Support/FigmaFusionBridge/Transfers` |
| Manifests | `~/Library/Application Support/FigmaFusionBridge/Manifests` |
| Session token | `~/Library/Application Support/FigmaFusionBridge/session.json` (mode 600) |
| Logs | `~/Library/Logs/FigmaFusionBridge/` |

Assets live in Application Support, not a temporary folder, on purpose: a Fusion
Loader stores a *path*, so assets in `/tmp` would break every existing
composition the next time macOS swept it.

## Uninstalling

1. Quit the app from the menu bar.
2. In the app before quitting, or by hand, remove:
   `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/Figma Fusion Bridge`
   and the matching `Utility` folder.
3. Delete `~/Library/Application Support/FigmaFusionBridge`.
4. In Figma: **Plugins ▸ Development**, remove the plugin.
