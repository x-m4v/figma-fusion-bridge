# Color management — verification status, 2026-09-11

Receive keeps source graphics in encoded sRGB and adds a native GamutConvert
boundary after their composite. In supported Resolve Color Managed contexts
it removes the sRGB transfer function and converts primaries to the Fusion
linear working space. This is not a universal display-match guarantee.

Supported detection: DaVinci YRGB Color Managed v2 with DWG/Intermediate,
Rec.709 or sRGB timeline primaries. Unmanaged YRGB retains encoded values and
reports a warning. Unknown contexts, including ACES, are blocked rather than
silently assigned a gamut. Existing colorHandling options do not override this
Receive path; legacy per-color linearisation is intentionally not applied twice.

Connect the final `FFBridge_sRGB_to_*` node to the destination, not Root_Merge:
bypassing the boundary bypasses the conversion. The CLI reports `outputTool`.
Do not route already color-managed footage through the source-graphics boundary.
Project color settings, grades and output transforms are not changed.

## Alpha and editability

GamutConvert uses PreDividePostMultiply for premultiplied RGB. Alpha is not
gamma-corrected. Shape and Text+ colors remain editable upstream. Compositing
before the boundary preserves the existing encoded-graphics workflow; it is
not a claim that every Figma blend/effect is reproduced exactly.

## Remaining limitations

- Source data is assumed sRGB. Display P3 documents and embedded image profiles
  have not been validated; Loader interpretation still needs image-based tests.
- Output DRT/tone mapping, HDR luminance, grades, Viewer LUTs and display profiles
  can change appearance after this conversion. No inverse DRT is attempted.
- The current project uses DWG/Intermediate and Rec.709 (Scene) output. That is
  not the same transfer function as sRGB; equal output numbers are not the test
  for equal displayed color.
- Automated tests verify graph configuration, not rendered pixel equality.
- Resolve Studio 21.0.3 accepted the native settings and current-comp connections.
  Other Resolve versions have not been validated.

## Validation still required before claiming visual fidelity

Render neutral ramps, saturated patches, brand colors, gradients and translucent
edges from Figma and Resolve into the same explicitly tagged output space.
Compare decoded values and visual appearance with identical display transforms.
Test solid graphics and Loader images separately to detect double conversion.
Do not use screenshots from differently configured viewers as a numeric oracle.

## Sources

- [Blackmagic DWG/Intermediate specification, corrected August 2021](https://documents.blackmagicdesign.com/InformationNotes/DaVinci_Resolve_17_Wide_Gamut_Intermediate.pdf)
- [Blackmagic Fusion scripting guide](https://documents.blackmagicdesign.com/UserManuals/Fusion8_Scripting_Guide.pdf)
- Installed Resolve 21 scripting SDK and native GamutConvert GetInputList / SaveSettings probes.
