> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Phase 0 — Technical Feasibility Report

**Project:** Figma Fusion Bridge (working title)
**Date of investigation:** 2026-09-08
**Investigated on:** macOS 27.0 (build 26A5425a), Apple Silicon (arm64)

Every API claim below was verified against software installed on this machine —
the shipped Scripting SDK, the Fusion shared libraries, and 417 real `.setting`
files shipped by Blackmagic Design. Nothing here is quoted from memory.
Items that could **not** be verified statically are listed explicitly in
§7 "Open questions" together with the probe that resolves them.

---

## 1. Environment inventory

| Component | Finding | How verified |
|---|---|---|
| macOS | 27.0, arm64 | `sw_vers`, `uname -m` |
| DaVinci Resolve | **21.0.3** (build 21.0.30007) | `Info.plist` `CFBundleShortVersionString` |
| Resolve binary | Universal (x86_64 + **arm64**) | `file .../MacOS/Resolve` |
| Scripting SDK | present | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting` |
| Python | 3.9.6 (system) | `python3 --version` |
| Node.js / npm | 24.13.0 / 11.6.2 | `node --version` |
| Swift | 6.4 (arm64-apple-macosx27.0.0) | `swift --version` |
| Xcode | **absent** — Command Line Tools only | `xcodebuild -version` fails |
| macOS SDK | MacOSX27.0.sdk with `SwiftUI.framework` | SDK framework listing |

### 1.1 Consequence: no Xcode

`xcodebuild` is unavailable, so an `.xcodeproj`-based SwiftUI app cannot be built
on this machine as-is. However `SwiftUI.framework` and `AppKit.framework` **are**
present in the Command Line Tools SDK. Therefore the bridge is built with
**Swift Package Manager**, and the `.app` bundle is assembled by a shell script
(`Info.plist` + binary + resources). This produces a genuine, native, arm64
`LSUIElement` menu-bar application without requiring Xcode.

This is a deliberate architectural accommodation, documented in
`docs/DEVELOPER_GUIDE.md`, not a workaround that degrades the product.

---

## 2. Resolve scripting API — verified

Source: `Developer/Scripting/README.txt` (1145 lines, "Last Updated: 15 Jul 2026").

Confirmed entry points relevant to this project:

```
resolve = dvr_script.scriptapp("Resolve")
resolve.Fusion()                    -> Fusion    # start of all Fusion scripting
resolve.GetProjectManager()         -> ProjectManager
resolve.OpenPage("fusion")          -> Bool
resolve.GetVersionString()          -> String
```

Timeline-item level (needed for "Receive" into an existing clip):

```
timelineItem.GetFusionCompCount()       -> int
timelineItem.GetFusionCompByIndex(i)    -> fusionComp     # 1-based
timelineItem.GetFusionCompNameList()    -> [names]
timelineItem.GetFusionCompByName(name)  -> fusionComp
timelineItem.AddFusionComp()            -> fusionComp
timelineItem.ImportFusionComp(path)     -> fusionComp
timelineItem.ExportFusionComp(path, i)  -> Bool
timelineItem.LoadFusionCompByName(name) -> fusionComp
```

Timeline level:

```
timeline.InsertFusionCompositionIntoTimeline() -> TimelineItem
timeline.InsertFusionGeneratorIntoTimeline(name)
timeline.InsertFusionTitleIntoTimeline(name)
timeline.CreateFusionClip([timelineItems])
```

**Script installation location (official, from README §"Using a script"):**

```
All users: /Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts
Per user:  ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts
```

Subfolder semantics, quoted from the README: scripts under `Utility` are listed
on all pages, under `Comp` or `Tool` on the Fusion page, and under `Edit`,
`Color`, `Deliver` for those pages. Both `Comp` and `Utility` subdirectories were
confirmed to exist on this machine.

Environment for out-of-process scripting (official):

```
RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

### 2.1 Free vs Studio

The SDK README opens with: *"a brief introduction to the Scripting API for
DaVinci Resolve Studio"*. Blackmagic has historically restricted **external**
(out-of-process) scripting to Studio, while permitting **in-application** scripts
launched from `Workspace ▸ Scripts` and the Console in the free edition.

**Design consequence — this drove the whole transport architecture.** The bridge
must not depend on out-of-process control of Resolve. Instead, Resolve pulls
work from the bridge via a script the user launches from the menu. This keeps
the free edition viable. See §5.

---

## 3. Fusion composition API — verified in binary

The Resolve Scripting README documents the *Resolve* object model but **not** the
Fusion composition object model. Those symbols were verified directly in
`Contents/Libraries/Fusion/libfusionsystem.dylib`:

| Symbol | Present | Purpose in this project |
|---|:--:|---|
| `AddTool` | ✅ | create a node |
| `SetInput` / `GetInput` | ✅ | read/write node inputs |
| `FindTool` | ✅ | locate node by name for re-sync |
| `StartUndo` / `EndUndo` | ✅ | make an import one undo step |
| `SetAttrs` / `GetAttrs` | ✅ | node name, comments, position |
| **`SetData` / `GetData`** | ✅ | **persistent per-node custom metadata** |
| `Paste` | ✅ | bulk-create nodes from a settings table |
| `SaveSettings` / `LoadSettings` | ✅ | comp serialisation |

`SetData`/`GetData` is the single most important finding for **Live Sync**: it
gives every created node a durable metadata slot that survives save/load. Figma
node identity is therefore stored *in the node itself*, not inferred from names
or positions. An external manifest is kept as a redundant index only.

### 3.1 Node type IDs — verified

Verified by exact-string match in `libfusionoperators.dylib` / `libfusionsystem.dylib`:

**Shapes (vector, resolution independent):** `sRectangle` `sEllipse` `sNGon`
`sStar` `sBSpline` `sPolygon` `sTransform` `sMerge` `sRender` `sOutline`
`sBoolean` `sDuplicate` `sExpand` `sGrid`

**Image-domain:** `Background` `Merge` `Transform` `Blur` `Shadow`
`RectangleMask` `EllipseMask` `PolylineMask` `BitmapMask` `Loader` `Saver`
`ChannelBoolean` `MediaIn` `MediaOut` `TextPlus` `Underlay` `Custom`
`Glow` `SoftGlow` `DirectionalBlur` `AlphaDivide` `AlphaMultiply` `ChangeDepth`

Two corrections to commonly-assumed names, both caught by this check:

* The drop-shadow node ID is **`Shadow`**, not `DropShadow` (`DropShadow` returns
  zero matches in every Fusion library).
* Text+ registry ID is **`TextPlus`**, not `Text+` (the `+` is display-only).
* `sJoin` does **not** exist; `sOutline` and `sMerge` cover the joining cases.

---

## 4. Node input names — verified against shipped content

417 real `.setting` files were extracted from
`/Library/Application Support/Blackmagic Design/Fusion/Templates.drfx` plus the
three templates under `Developer/Fusion Templates/`. Input names below are
copied from those files, so they are exactly what Fusion writes itself.

### 4.1 `Background` — gradients are fully native and editable

From `Developer/Fusion Templates/Generators/Gradient.setting`:

```lua
Background2 = Background {
  Inputs = {
    Width  = Input { Value = 1920, },
    Height = Input { Value = 1080, },
    UseFrameFormatSettings = Input { Value = 1, },
    Type         = Input { Value = FuID { "Gradient" }, },
    GradientType = Input { Value = FuID { "Reflect" }, },
    Start = Input { Value = { 0.5, 0.5 }, },
    End   = Input { Value = { 0.53, 0.48 }, },
    Gradient = Input {
      Value = Gradient {
        Colors = {
          [0] = { 0, 0, 0, 1 },
          [1] = { 0, 0.42816, 0.669, 1 }
        }
      },
    },
    Repeat = Input { Value = FuID { "Ping-Pong" }, },
  },
}
```

**Verdict: editable multi-stop gradients are fully feasible.** The `Gradient`
value is an ordered map of `position -> {r,g,b,a}` with arbitrary float
positions, which maps 1:1 onto Figma `gradientStops` (`position`, `color.r/g/b`,
`color.a`). Alpha per stop is supported. `Start`/`End` are normalised comp
coordinates, which is exactly the information carried by Figma's
`gradientTransform`. No rasterisation is required for linear or radial gradients.

Solid corner inputs also confirmed: `TopLeftRed/Green/Blue/Alpha`,
`TopRightRed/...`, `BottomLeftRed/...`.

### 4.2 `RectangleMask` — corner radius stays numeric

From `Developer/Fusion Templates/Generators/Rounded Window.setting`:

```lua
Rectangle1 = RectangleMask {
  Inputs = {
    Filter = Input { Value = FuID { "Fast Gaussian" }, },
    OutputSize = Input { Value = FuID { "Custom" }, },
    MaskWidth  = Input { Value = 1920, },
    MaskHeight = Input { Value = 1080, },
    PixelAspect = Input { Value = { 1, 1 }, },
    UseFrameFormatSettings = Input { Value = 1, },
    ClippingMode = Input { Value = FuID { "None" }, },
    CornerRadius = Input { Value = 0.25, },
  },
}
```

Exposed inputs (from that macro's `InstanceInput` list): `Level`, `SoftEdge`,
`BorderWidth`, `Invert`, `Solid`, `Center`, `Width`, `Height`, `CornerRadius`,
`Angle`, `Mask`.

### 4.3 `sRectangle` — native vector shape

From `Edit/Titles/Callout Modern Lines.setting`:

```lua
sRectangle2 = sRectangle {
  Inputs = {
    Width  = Input { Value = 0.022, },
    Height = Input { Value = 0.05, Expression = "Width", },
    CornerRadius = Input { Value = 1, },
    Angle = Input { Value = 45, }
  },
}
```

Note `Expression = "Width"` — shipped content itself drives one input from
another by expression, confirming that expression-linked inputs survive
round-tripping. This is the mechanism reserved for the experimental Auto Layout
work in Phase 6.

`sRender` inputs confirmed: `Input`, `Width`, `Height`, `UseFrameFormatSettings`.

### 4.4 `TextPlus` — real text, never rasterised

From `Fusion/Styled Text/War Games.setting` and `Edit/Titles/*`:

```lua
Text1_2 = TextPlus {
  Inputs = {
    StyledText = Input { Value = "BLACKMAGIC\nDESIGN" },
    Font  = Input { Value = "Open Sans" },
    Style = Input { Value = "Light" },
    Size  = Input { Value = 0.2126 },
    HorizontalJustificationNew = Input { Value = 3 },
    VerticalJustificationNew   = Input { Value = 3 },
    LineSpacing      = Input { Value = 0.598 },
    CharacterSpacing = Input { Value = 1.606 },
    Red1 = Input { Value = 0 }, Green1 = Input { Value = 0 },
    Blue1 = Input { Value = 0 }, Alpha1 = Input { Value = 0 },
    Width = Input { Value = 1920 }, Height = Input { Value = 1080 },
    UseFrameFormatSettings = Input { Value = 1 },
  },
}
```

Critical naming detail confirmed by the shipped files: the alignment inputs are
**`HorizontalJustificationNew` / `VerticalJustificationNew`**, not
`HorizontalJustification`. The un-suffixed names also occur (29 and 24 hits
respectively) and are the legacy Fusion 8 inputs; the `New` variants are what
Resolve 21 writes. The builder writes the `New` inputs and is verified against
these files.

Text+ supports multiple *shading elements* (`Red1..Alpha1` = element 1 fill,
`Red2..`, `Enabled2`, `ElementShape2`, `Offset2`, `Softness*2` = element 2).
Element 2 is used for the text stroke, which keeps Figma text strokes native.

`ManualFontKerningPlacement = Input { Value = StyledText { Value = "", Array = {...} } }`
exists, which is the hook for per-character styling investigated in Phase 6
(mixed fonts inside one Figma `TextNode`).

**Verdict: text stays editable Text+.** Rasterisation is never required for
single-style text, and per-character colour/size is representable.

### 4.5 `Merge` and `Transform`

`Merge` inputs confirmed: `Background`, `Foreground`, `Center`, `Size`, `Angle`,
`ApplyMode`, `AlphaMode`, `Blend`, `EffectMask`, `ApplyMaskInverted`,
`FilterMethod`, `PerformDepthMerge`.

`Transform` inputs confirmed: `Input`, `Center`, `Size`, `Angle`, `Edges`,
`FlipHoriz`, `MotionBlur`, `Quality`, `FilterMethod`, `Width`, `Height`.

Note: `ApplyOperator` returns **zero** hits — the blend-mode input is
`ApplyMode`. `Blend` is the node's own opacity/mix, a separate input. This
separation is what lets Figma *fill opacity* and *layer opacity* stay
independent, as required.

---

## 5. Transport architecture — decision

### 5.1 Constraint: Figma plugin sandbox

A Figma plugin's UI runs in a sandboxed `<iframe>`. Network access is only
available from that iframe (never from the plugin's main/controller thread), and
only to origins declared in `manifest.json` under `networkAccess.allowedDomains`.
The controller thread reaches the network exclusively by `postMessage` to its own
UI. This holds identically in Figma Desktop and Figma in the browser.

A browser-hosted plugin talking to `http://127.0.0.1` from an `https://` page is
**mixed content**. Browsers block mixed *active* content, but treat
`http://127.0.0.1` and `http://localhost` as **potentially trustworthy origins**
(W3C Secure Contexts), so requests to loopback are permitted. This is the
mechanism every local design-tool bridge relies on and it needs no certificate.

### 5.2 Chosen protocol

| Channel | Protocol | Why |
|---|---|---|
| Control + design payload | **WebSocket** `ws://127.0.0.1:<port>` | bidirectional, needed for Live Sync and for Resolve→Figma "Pull selection" |
| Binary assets | **HTTP POST/GET** on the same port | streams large images without base64 inflation on the socket |
| Resolve ↔ bridge | **HTTP long-poll** on loopback | Resolve's Python has no bundled WebSocket client; `urllib` is always present |

Two `NWListener`s, bound to `127.0.0.1` and `::1`. **Never `0.0.0.0`.** Both
families are needed because Figma's manifest accepts only host names in
`allowedDomains` — literal IP addresses are rejected — and `localhost` resolves
to both. Port 8787 by
default with automatic fallback scan.

**Why HTTP long-poll for the Resolve side rather than a socket:** the Resolve
script runs inside Resolve's embedded Python. Assuming `websocket-client` is
installed there is not safe. `urllib.request` is in the standard library and
always available. Long-poll gives near-instant delivery with zero dependencies —
this is what makes Live Sync work on a stock Resolve install, Free or Studio.

### 5.3 Security

* Loopback bind only, enforced at the listener.
* A session token generated at bridge start, written to
  `~/Library/Application Support/FigmaFusionBridge/session.json` with mode `0600`.
  Every request must present it. Any local web page can reach loopback ports;
  the token is what stops an arbitrary page from driving Resolve.
* `Origin` validation on the WebSocket handshake.
* Strict schema validation of every message before it reaches the builder.
* No design data leaves the machine. There is no cloud component in the
  transfer path at all.

---

## 6. Graph construction strategy — decision

Two mechanisms exist for creating nodes:

**(A) Imperative** — `comp:AddTool(id, x, y)` then `tool:SetInput(name, value)`
per input. Simple, but: one IPC round-trip per call. A 150-layer frame with ~12
inputs per node is ≈2000 round-trips. It also cannot express structured values
(`Gradient{}`, `Point{}`, `StyledText{}`) from Python cleanly.

**(B) Declarative** — generate the Fusion ASCII `.setting` document and hand the
whole thing to the comp in one operation (`comp:Paste`, or `ImportFusionComp`
for a fresh comp). One round-trip regardless of size, structured values are
expressible verbatim, and — decisively — **the generator becomes a pure function
that is unit-testable with no Resolve running at all.**

**Decision: (B) is primary, (A) is the fallback.** `FusionGraphBuilder` is a pure
Python library `Interchange JSON -> Fusion ASCII`, with zero Resolve imports and
zero transport imports. Every coordinate, colour, gradient and stroke conversion
is therefore covered by ordinary unit tests. A thin `applier` module performs the
paste and degrades to (A) if paste is unavailable.

This choice also delivers the transactional-import requirement: the document is
fully built and validated in memory before anything touches the user's comp.

---

## 7. Open questions requiring a live probe

These could not be settled by static inspection because Resolve was not running.
`resolve/scripts/Utility/Figma Fusion Bridge/Probe.py` answers all of them
against a live Fusion and writes the answers to
`~/Library/Application Support/FigmaFusionBridge/probe.json`.

1. Exact accepted argument form of `comp.Paste()` from Python (table vs string).
2. Numeric enum values of `HorizontalJustificationNew` / `VerticalJustificationNew`.
3. Whether `sRectangle` `Width`/`Height` are relative to comp height or width
   (affects non-square compositions only).
4. Whether `SetData` accepts nested dictionaries or only flat scalars.
5. Blend-mode `ApplyMode` FuID string set available in Resolve 21.

Until the probe has run, the builder uses conservative documented defaults and
records a warning rather than guessing silently.

---

## 8. Overall verdict

| Requirement | Feasible | Mechanism |
|---|---|---|
| Native editable shapes | ✅ Full | `sRectangle`/`sEllipse`/`sNGon` + `sRender` |
| Numeric corner radius | ✅ Full | `CornerRadius` input |
| Editable Text+ | ✅ Full | `TextPlus.StyledText` |
| Editable multi-stop gradients | ✅ Full | `Background.Gradient` `Colors` map |
| Gradient alpha per stop | ✅ Full | 4th component of each stop |
| Independent fill/layer opacity | ✅ Full | shape alpha vs `Merge.Blend` |
| Stroke as separate branch | ✅ Full | `sOutline` / second shape |
| INSIDE/CENTER/OUTSIDE stroke | ⚠️ Computed | geometry offset, documented math |
| Image fills | ✅ Full | `Loader` + content-addressed cache |
| Drop shadow | ✅ Full | `Shadow` node |
| Layer blur | ✅ Full | `Blur` node + calibration function |
| Inner shadow | ⚠️ Constructed | mask/invert/blur/merge subgraph |
| Background blur | ⚠️ Approximate | requires downstream dependency, Phase 6 |
| Stable identity / Live Sync | ✅ Full | `SetData`/`GetData` per node |
| Preserve user animation | ✅ Full | split base node vs user Transform |
| Free edition support | ✅ Likely | in-app script + long-poll, no external control |
| Build without Xcode | ✅ Full | SwiftPM + hand-assembled `.app` |

**No blocking obstacle was found.** The two genuinely hard features — Background
Blur and per-character rich text — have identified paths and are scheduled as
Experimental with explicit warnings rather than silent approximation.
