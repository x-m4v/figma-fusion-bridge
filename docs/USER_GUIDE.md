> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# User guide

## The idea

Design in Figma. Animate in Fusion. Change the design. Sync. Keep animating.

The bridge sends the *structure* of your design, not a picture of it. A button
arrives as a shape you can round, a gradient you can re-ramp and text you can
retype — so revisions cost a re-sync instead of a rebuild.

## The Figma plugin

**Status lights** — Bridge, DaVinci Resolve, Fusion. Green means ready.

**Selection** — what will be sent, and how many layers it contains. Select a
frame, a group, a component, an instance, or any set of layers.

**Send to Fusion** — reads the selection, uploads anything new, queues it.

**Live Sync** — resend automatically after each edit, debounced by about a
second. A continuous drag sends once, when you stop.

**Options**

| Option | Choices | What it does |
|---|---|---|
| Vector shapes | Native only · Automatic · Always image | How hard to try rebuilding paths as Fusion shapes |
| Clip frames | Follow Figma · Always · Never | Whether frame contents are clipped |
| Colour | Match Figma (sRGB) · Use project colour | See [Colour](#colour) |
| Preserve hierarchy | on/off | Off flattens everything to one level |
| Include hidden layers | off by default | Hidden layers are usually hidden on purpose |
| Flatten unsupported layers | on | Export what cannot be rebuilt, rather than skipping it |

**Transfer log** — every warning, by layer name. Read it before switching apps;
it is much cheaper to fix a missing font in Figma than in Resolve.

## Receiving in Resolve

**Workspace → Scripts → Figma Fusion Bridge - …**

* **Receive** — bring in the latest transfer.
* **Receive Into Current Composition** — add it to the composition you have
  open, without disturbing the graph already there. Re-running this updates the
  layers it created before instead of duplicating them.
* **Pull Current Figma Selection** — ask Figma for whatever is selected right
  now, without leaving Resolve.

The Console prints a report:

```
──────────────────────────────────────────────────────────
  Figma Fusion Bridge — Received
──────────────────────────────────────────────────────────
  20 nodes · 1 assets · 34 ms
  Import path: paste · Composition: 1920x1080

  ⚠ "Headline" The font "Neue Haas Grotesk Display Pro Medium" is not
    installed on this Mac. Text is created with the original font name…
  ✓ 2 layer(s) updated, 1 added, 0 no longer in the design.

  0 error(s), 1 warning(s)
```

## Reading the node graph

Each layer becomes a branch feeding a single composite spine:

```
CTA_Button_Shape ─→ CTA_Button_Fill ──┐
CTA_Button_Stroke ─→ …_StrokeRender ──┴─→ …_FillStroke ─→ …_Shadow ─→ CTA_Button_Anim ─┐
                                                                                       ├─→ Root_Merge
Label_Text ─→ Label_TextPlace ─→ Label_Anim ───────────────────────────────────────────┘
```

Names come from your layer names. The suffix says what the node is: `_Shape`,
`_Stroke`, `_Fill`, `_Shadow`, `_Anim`, `_Merge`.

## Animating so re-sync keeps your work

**Put keyframes on the `*_Anim` Transform.** Every layer has one, and the sync
never writes to it — it is created once and then belongs to you.

Safe after a re-sync:

* Keyframes on any `*_Anim` node
* New nodes you added yourself
* Anything downstream of the imported graph

Rebuilt by a re-sync, so do not animate directly:

* `*_Shape`, `*_Stroke`, `*_Fill` — geometry comes from the design
* `*_Shadow`, `*_Blur` — effect settings come from the design
* `*_Merge` — reconnected, and Blend/ApplyMode refreshed

If a layer disappears from the Figma document, its Fusion nodes are **kept** and
you get a warning. That is deliberate: an accidental deletion in Figma must not
destroy an evening's animation.

## Colour

Figma is sRGB. Your Resolve project may not be.

* **Match Figma (sRGB)** — values pass through unchanged. Correct for a plain
  DaVinci YRGB project. What you see in Figma is what you get.
* **Use project colour** — values are linearised with the exact sRGB transfer
  function and handed to Resolve's colour management. Correct for YRGB Color
  Managed and ACES.

If brand colours look off, this is the first thing to change.

## Fonts

The bridge never substitutes a font quietly. Three outcomes:

* **Found** — nothing to do.
* **Family found, weight missing** — the nearest weight is used and warned.
* **Not installed** — the `Text+` keeps the original font name and warns.
  Install the font and it appears correctly, with no re-import.

## Images

Stored by content hash under
`~/Library/Application Support/FigmaFusionBridge/Assets`, so the same photo used
twenty times is one file and one upload. Re-sending a design full of photos
transfers almost nothing the second time. Size and a Clear button are in
**Settings ▸ Asset cache**.

## Ten workflows

1. **UI motion.** Import a product screen, animate cards and buttons on their
   `_Anim` transforms, keep the layout exactly on-brand.
2. **YouTube lower thirds.** Build the design once, animate once, re-sync per
   episode when the text changes.
3. **Vertical social.** A 1080×1920 Figma frame into a matching timeline, 1:1
   pixels, no scaling guesswork.
4. **Broadcast scoreboards.** Native shapes stay crisp when the graphic package
   is re-rendered at 4K.
5. **Product video callouts.** Labels stay `Text+`, so wording changes are a
   retype, not a re-export.
6. **Animated typography.** Poster layouts arrive as real text with real
   tracking and leading.
7. **Title sequences.** Style frames become a structured graph instead of a
   reference image to eyeball.
8. **Explainer graphics.** Diagrams keep their hierarchy, so you can animate
   whole groups.
9. **Presentation builds.** Slide layouts import with z-order intact, ready for
   staggered reveals.
10. **Client revisions.** The designer changes Figma, you press Receive, your
    animation is still there. This is the one the whole design is for.

## Keyboard

The plugin follows Figma's own shortcuts. The bridge registers no global
shortcuts by default, deliberately — a background utility should not take a key
combination away from the apps you are working in.
