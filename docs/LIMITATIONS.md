> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Limitations

Everything the bridge cannot do exactly. Each entry says what happens instead
and whether you get a warning. Nothing in this list fails silently.

## Support levels

| Level | Meaning |
|---|---|
| **Full** | Matches the design, and stays editable in Fusion |
| **Computed** | Exact result, reached by constructing geometry rather than setting one control |
| **Approximate** | Visually close, mathematically different. Always warned |
| **Experimental** | Built, but may differ noticeably in complex cases. Always warned |
| **Unsupported** | Not reproduced. Always warned, never silent |

## Shapes and geometry

| Figma | Fusion | Level | Notes |
|---|---|---|---|
| Rectangle | `sRectangle` | Full | |
| Rounded rectangle | `sRectangle` + `CornerRadius` | Full | Stays a numeric control |
| Per-corner radii | `sRectangle` | **Approximate** | Fusion shapes take one radius; the largest is used |
| Corner smoothing (squircle) | — | **Unsupported** | Plain rounded corners are used |
| Ellipse | `sEllipse` | Full | |
| Arc / donut ellipse | `sEllipse` | **Approximate** | Drawn as a full ellipse; Fusion's shape has no sweep |
| Polygon | `sNGon` | Full | Side count stays editable |
| Star | `sStar` | Full | |
| Line | `sRectangle` + stroke | Full | |
| Custom vector path | SVG asset | **Approximate** | Exported as SVG, not rebuilt as a Fusion spline |
| Boolean operation | SVG asset | **Approximate** | Resolved geometry, not a live `sBoolean` |

## Paint

| Figma | Fusion | Level | Notes |
|---|---|---|---|
| Solid fill | Shape colour | Full | |
| Linear gradient | `Background` gradient | Full | Every stop, every alpha |
| Radial gradient | `Background` radial | Full | |
| Angular gradient | `Background` angle | **Approximate** | Sweep start may differ |
| Diamond gradient | `Background` square | **Approximate** | Fusion has no diamond; corners differ |
| Image fill | `Loader` + `Transform` | Full | |
| Image `TILE` / `CROP` | `Loader` + `Transform` | **Approximate** | Check framing |
| Video fill | — | **Unsupported** | Add the video in Resolve |
| Pattern fill | — | **Unsupported** | Named in the warning |
| Multiple fills | Merge chain | Full | |

## Stroke

| Figma | Fusion | Level | Notes |
|---|---|---|---|
| Solid stroke | Second shape, `Solid = 0` | Full | Its own branch, not baked into the fill |
| Gradient stroke | Shape masking a gradient | Full | Never rasterised |
| `CENTER` alignment | Same path | Full | |
| `INSIDE` / `OUTSIDE` | Offset path | **Computed** | Exact for rectangles and polygons |
| Inside stroke on an ellipse | Offset ellipse | **Approximate** | Warned only when thick enough to see |
| Stroke thicker than the shape | Filled shape | **Approximate** | Warned |
| Dashed stroke | Solid stroke | **Unsupported** | Use a Duplicate or Paint node |
| Stroke caps / joins | — | **Approximate** | Fusion shape strokes have limited control |
| Image stroke | Flat colour | **Unsupported** | Warned |

## Text

| Figma | Fusion | Level | Notes |
|---|---|---|---|
| Characters | `Text+` `StyledText` | Full | Retype it in Resolve |
| Multi-line | `StyledText` with `\n` | Full | |
| Font family and style | `Font` / `Style` | Full | Resolved against installed fonts |
| Missing font | Original name kept | **Warned** | Never silently substituted — install the font and it appears |
| Size, letter spacing, line height | `Size`, `CharacterSpacing`, `LineSpacing` | Full | |
| Horizontal / vertical alignment | `…JustificationNew` | Full | |
| Justified | Fusion justify | **Approximate** | Line breaks may fall differently |
| Mixed styles in one text layer | One `Text+`, dominant style | **Approximate** | Stays editable; warned |
| Gradient or image fill on text | White `Text+` | **Approximate** | Re-colour in Fusion; warned |
| Paragraph spacing / indent | — | **Unsupported** | Captured in the transfer, not applied |

## Effects

| Figma | Fusion | Level | Notes |
|---|---|---|---|
| Drop shadow | `Shadow` | Full | |
| Shadow spread | Widened softness | **Approximate** | Fusion has no spread; warned |
| Layer blur | `Blur` | Full | Resolution-independent conversion |
| Inner shadow | Matte → invert → blur → merge | **Computed** | Built from real, editable nodes |
| Background blur | Branch and re-merge | **Experimental** | Warned; can differ where layers overlap |
| Noise / texture effects | — | **Unsupported** | Named in the warning |

## Blend modes

Exact: Multiply, Screen, Overlay, Difference, Lighten, Color Burn, Color Dodge,
Hard Light, Soft Light, Linear Burn.

**Approximate** (warned): Darken → `DarkerColor` (Fusion compares composite
luminance, Figma per channel); Linear Dodge → `LinearLight`; Exclusion →
`Difference`.

**Unsupported** (warned, merged normally): Hue, Saturation, Color, Luminosity.
These are non-separable — they need a colour-space subgraph that a Merge cannot
express, and faking them per channel would look wrong in a way that is hard to
diagnose.

## Structure

| Figma | Level | Notes |
|---|---|---|
| Frames, groups, components, instances | Full | Hierarchy and z-order preserved |
| Nested groups | Full | |
| Clip content | Full | `RectangleMask`; honours Figma, or force On/Off |
| Masks | Full | Alpha masks via `EffectMask` |
| Auto Layout | **Baked** | Current positions are imported. Live layout is not yet rebuilt |
| Component variants | **Approximate** | The rendered variant is imported |

## Colour

Figma is sRGB. A Resolve project may be Rec.709, DaVinci Wide Gamut, ACES or
HDR, and a Fusion composition inherits that — so the RGB numbers are not
unconditionally transferable.

* **Match Figma (sRGB)** — pass values through. Right for plain DaVinci YRGB.
* **Use project colour** — linearise with the exact sRGB EOTF and let Resolve's
  colour management carry them. Right for YRGB Color Managed and ACES.

Only sRGB / Rec.709 primaries are implemented. Wide-gamut primary conversion is
not, and the setting says so rather than doing something plausible-looking.

## Known gaps

* Auto Layout is imported as baked positions. The transfer already carries the
  layout spec, so live rebuilding is additive work, not a redesign.
* Per-character rich text uses the dominant style. `Text+` exposes
  `ManualFontKerningPlacement`, which is the path to true per-character styling.
* Resolve-initiated **Pull Current Figma Selection** needs the plugin to hold an
  open channel; it currently reports "nothing to receive" when it cannot.
* No visual regression suite yet. The conversion maths is unit-tested; pixel
  comparison against Figma renders is not automated.
