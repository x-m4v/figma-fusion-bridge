> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Troubleshooting

Start with **Workspace → Scripts → Figma Fusion Bridge - Connection
Test** inside Resolve. It checks every link in the chain and names the broken
one.

---

### The plugin says "Bridge not running"

The app is not open, or it could not take a port.

* Look for the branch icon in the menu bar. If it is missing, open the app.
* Check it is listening: `curl http://127.0.0.1:8787/api/hello`
* If another program holds 8787, the bridge tries 8788–8791 automatically. The
  port it settled on is shown in the app's **Status** tab and in
  `~/Library/Logs/FigmaFusionBridge/bridge.log`.

### The pairing code is not accepted

* Codes expire after ten minutes. Press **New code** and try again.
* The alphabet deliberately excludes `0`, `O`, `1`, `I` and `L`, so if you think
  you see one, it is something else.
* Case and stray spaces do not matter.

### Resolve has no "Figma Fusion Bridge" menu

* Install the scripts: bridge app ▸ **Setup ▸ Install scripts**.
* **Restart Resolve.** It scans its Scripts folder only at startup. This is the
  most common cause by a wide margin.
* Confirm the files exist:
  ```bash
  ls ~/Library/Application\ Support/Blackmagic\ Design/DaVinci\ Resolve/Fusion/Scripts/Comp/
  ```

### "Figma Fusion Bridge is not installed correctly"

The scripts are present but the Python library is not. Use **Setup ▸ Reinstall**
in the app. Check:

```bash
ls ~/Library/Application\ Support/FigmaFusionBridge/lib/ffbridge/
```

### Receive says "There is nothing waiting to be received"

Nothing has been sent since the bridge started. Select something in Figma and
press **Send to Fusion** first. If you did, check the plugin's transfer log for
an error.

### "There is no open Fusion composition"

Receive needs somewhere to put the graph. On the Edit page, select a clip and
switch to the Fusion page — or add a Fusion composition to the timeline first.

### A font came in wrong

The bridge never substitutes a font silently. If the log says
`Font "X" is not installed on this Mac`, the `Text+` node keeps the original
font name, so **installing the font makes it appear correctly without
re-importing**.

If the family exists but the weight does not, you get
`… is installed but not the "Medium" style` and the nearest weight. Same fix.

### A gradient looks different

* Angular and diamond gradients are approximated — see
  [LIMITATIONS.md](LIMITATIONS.md).
* If a gradient arrived as a flat colour, the log will contain
  `GRADIENT_DEGRADED`. That means the import fell back to the node-by-node path,
  which cannot carry a gradient value. The warning includes the path to a
  `.setting` file containing the full gradient — drag it into the node graph.

### Colours do not match

Your Resolve project is probably colour-managed. In the plugin's **Options**,
switch **Colour** from *Match Figma (sRGB)* to *Use project colour*. See
[LIMITATIONS.md § Colour](LIMITATIONS.md#colour).

### An image is missing

`ASSET_MISSING` means the transfer referenced an image the cache does not have.
Send again — the plugin uploads anything the bridge does not already hold. If it
persists, clear the cache in **Settings ▸ Asset cache** and resend.

### Re-syncing duplicated everything

Identity comes from the Figma layer id, stored on each Fusion node. Duplication
means the bridge could not find the previous nodes:

* The graph was pasted into a *different* composition than last time. Manifests
  are per composition.
* The nodes were copied to a new comp, which does not carry their manifest.

Delete the duplicates and re-send once; the new manifest becomes the baseline.

### My animation was overwritten

It should not be. Keyframes belong on the `*_Anim` Transform of each layer,
which the sync never writes to. If you animated a `*_Shape` or `*_Merge` node
directly, that node *is* rebuilt on sync. Move those keyframes to `*_Anim`.

### Live Sync stopped

* It debounces about a second after your last edit; a continuous drag sends once
  at the end, by design.
* It pauses while a transfer is in flight.
* Toggle it off and on to restart it.

### Where are the logs

```
~/Library/Logs/FigmaFusionBridge/bridge.log     macOS app
~/Library/Logs/FigmaFusionBridge/resolve.log    Resolve scripts
```

**Settings ▸ Diagnostics ▸ Export diagnostic report** reveals them in Finder.
They contain paths, timings and layer names — no design content.
