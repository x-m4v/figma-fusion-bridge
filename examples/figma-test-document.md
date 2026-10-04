# Coverage test document

Build this once in Figma. A single **Send to Fusion** then exercises every path
in the builder and every diagnostic it can emit, which makes it the fastest way
to check a change end to end.

Lay it out as a 1920×1080 frame named `Coverage`, with one labelled row per
group so a visual comparison against the Fusion render is easy to read.

## Row 1 — shapes

| Layer | Set up | Expect |
|---|---|---|
| `Rect Plain` | 200×100 rectangle | `sRectangle`, Full |
| `Rect Rounded` | radius 24 | `CornerRadius` 0.48, editable |
| `Rect Pill` | radius = half the height | `CornerRadius` 1.0 |
| `Rect Mixed Radii` | 0 / 24 / 0 / 24 | Warning `MIXED_CORNER_RADIUS` |
| `Rect Smoothed` | corner smoothing 60% | Warning `CORNER_SMOOTHING_UNSUPPORTED` |
| `Ellipse` | 120×120 | `sEllipse` |
| `Ellipse Arc` | 40–320° sweep | Warning `ARC_UNSUPPORTED` |
| `Polygon 6` | 6 sides | `sNGon`, `Sides = 6` |
| `Star 5` | 5 points | `sStar` |
| `Line` | 200 px, 4 px stroke | `sRectangle` + stroke |
| `Vector Custom` | any pen-tool path | Info `VECTOR_EXPORTED_AS_SVG` |
| `Bool Subtract` | two shapes, Subtract | SVG asset |

## Row 2 — paint

| Layer | Set up | Expect |
|---|---|---|
| `Fill Solid` | any colour | shape colour |
| `Fill Solid 40%` | fill opacity 40% | shape alpha 0.4 |
| `Layer 70%` | layer opacity 70%, fill 100% | `Merge.Blend` 0.7 |
| `Fill 40 Layer 70` | fill 40%, layer 70% | **alpha 0.4 and Blend 0.7 — never 0.28** |
| `Gradient Linear` | 3 stops | `Background`, 3 stops |
| `Gradient Alpha` | middle stop at 50% alpha | alpha preserved per stop |
| `Gradient Radial` | 2 stops | `GradientType = Radial` |
| `Gradient Angular` | 2 stops | Warning `GRADIENT_APPROXIMATED` |
| `Gradient Diamond` | 2 stops | Warning `GRADIENT_APPROXIMATED` |
| `Gradient 45` | rotate the gradient 45° | endpoints, not an angle |
| `Fill Image` | any photo, Fill | `Loader` |
| `Fill Image Crop` | same photo, Crop | Warning `IMAGE_SCALE_MODE_APPROXIMATED` |
| `Fill Stacked` | solid + gradient + image | Merge chain |

## Row 3 — stroke

| Layer | Set up | Expect |
|---|---|---|
| `Stroke Center` | 10 px, Center | outline path 200×100 |
| `Stroke Inside` | 10 px, Inside | outline path 190×90 |
| `Stroke Outside` | 10 px, Outside | outline path 210×110 |
| `Stroke Gradient` | gradient stroke | `Background` masked by the outline — no raster |
| `Stroke Dashed` | dash 8 / 8 | Warning `STROKE_DASHED` |
| `Stroke Overthick` | 20×20 shape, 40 px inside | Warning `STROKE_GEOMETRY` |
| `Stroke Ellipse Thick` | 100×100, 40 px outside | Warning about approximation |

## Row 4 — text

| Layer | Set up | Expect |
|---|---|---|
| `Text Basic` | one line | `Text+`, editable |
| `Text Multiline` | three lines | `\n` inside `StyledText` |
| `Text Left/Center/Right` | three layers | `HorizontalJustificationNew` 0 / 1 / 2 |
| `Text Justified` | justified | Info `TEXT_JUSTIFIED` |
| `Text Top/Middle/Bottom` | three layers | `VerticalJustificationNew` 0 / 1 / 2 |
| `Text Tracking` | letter spacing +10% | `CharacterSpacing` 1.1 |
| `Text Leading` | line height 150% | `LineSpacing` 1.5 |
| `Text Mixed` | two fonts in one layer | Warning `TEXT_MIXED_STYLES` |
| `Text Missing Font` | a font you do not have | Warning `FONT_MISSING`, original name kept |
| `Text Gradient Fill` | gradient on text | Warning `TEXT_FILL_APPROXIMATED` |

## Row 5 — effects

| Layer | Set up | Expect |
|---|---|---|
| `Drop Shadow` | 0 / 4, blur 12 | `Shadow` |
| `Drop Shadow Spread` | spread 8 | Warning `SHADOW_SPREAD` |
| `Inner Shadow` | 0 / 2, blur 6 | `ChannelBoolean` + `Blur` + `Merge`, Info `INNER_SHADOW_BUILT` |
| `Layer Blur` | 12 | `Blur` |
| `Background Blur` | 20 | Warning `BACKGROUND_BLUR_EXPERIMENTAL` |
| `Blend Multiply` | Multiply | `ApplyMode = Multiply` |
| `Blend Linear Burn` | Linear Burn | `ApplyMode = LinearBurn` (no space) |
| `Blend Hue` | Hue | Warning `BLEND_MODE_APPROXIMATED` |

## Row 6 — structure and transform

| Layer | Set up | Expect |
|---|---|---|
| `Group Nested` | group inside a group | hierarchy preserved |
| `Frame Clipped` | clip content on, child overflowing | `RectangleMask` |
| `Frame Unclipped` | clip content off | no mask |
| `Component` / `Instance` | one of each | component ids recorded |
| `Mask Alpha` | a shape masking siblings | `EffectMask` |
| `Rotated 45` | rotate 45° | Fusion `Angle` −45, centred on the real centre |
| `Rotated 90 Offset` | rotate 90°, away from the origin | centre from the transform, not `x + w/2` |
| `Flipped` | negative scale | mirrored, rotation unchanged |
| `Hidden` | visibility off | skipped unless "Include hidden" is on |
| `Locked` | locked | imported normally |
| `Auto Layout` | horizontal, 16 gap, 24 padding | baked positions |

## Comparing the result

1. In Figma, export `Coverage` as PNG at 1× → `reference.png`.
2. In Resolve, Receive into a 1920×1080 composition and render one frame →
   `result.png`.
3. Compare them. Differences should be limited to the rows the transfer log
   already warned about; anything else is a bug.
