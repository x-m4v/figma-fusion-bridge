> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/1.1.0/).
This project uses semantic versioning; the interchange schema is versioned
independently and is currently **1.0.0**.

## [0.1.0] — 2026-09-08

First working release. Everything below was built and verified against
DaVinci Resolve 21.0.3 on macOS 27 (Apple Silicon).

### Added

**Interchange format 1.0.0** — versioned, source-agnostic design document with
compatibility checking and referential-integrity validation.

**Figma plugin** — reads a selection into the interchange format: transforms,
geometry, fills, strokes, effects, text with styled segments, image fills,
components and instances, masks, clipping and Auto Layout metadata. Chunked and
cancellable; content-hashes assets so repeats are never re-uploaded.

**macOS bridge** — native arm64 menu-bar app. Loopback-only HTTP server, pairing
with an expiring six-character code, content-addressed asset cache, transfer
history, Resolve detection and script installation.

**Fusion graph builder** — interchange JSON to Fusion ASCII, as a pure function:

* Native shapes: `sRectangle`, `sEllipse`, `sNGon`, `sStar` with editable
  corner radius and side count
* Real `Text+` with font resolution against installed fonts
* Native gradients with every stop and per-stop alpha
* Strokes as their own branch, with `INSIDE`/`CENTER`/`OUTSIDE` reproduced
  geometrically
* Drop shadow, layer blur, and inner shadow built from real editable nodes
* Hierarchy, z-order, masks and frame clipping preserved
* A per-layer `*_Anim` Transform that re-sync never writes to

**Resolve scripts** — Receive, Receive Into Current Composition, Pull Current
Figma Selection, Connection Test.

**Tests** — 288 total (244 Python, 44 Swift), none requiring Figma, Resolve or
Xcode.

**Documentation** — feasibility report, architecture, installation, user guide,
developer guide, troubleshooting, limitations, and a typeset PDF manual.

### Notes on this release

* Auto Layout is imported as baked positions. The layout spec travels in the
  document already, so live rebuilding is additive work.
* Background blur is Experimental and always warned.
* Per-character rich text uses the dominant style and warns.
* No visual regression suite yet; conversion maths is unit-tested, pixel
  comparison is not automated.

### Verified during development

* API surface checked against the installed Resolve SDK and 417 shipped Fusion
  `.setting` files rather than from memory. This caught `Shadow` (not
  `DropShadow`), `TextPlus` (not `Text+`), `HorizontalJustificationNew` (not
  `HorizontalJustification`), and Fusion's inconsistently-spaced blend-mode
  identifiers.
* Font enumeration moved from `system_profiler` — which returns an empty
  document on macOS 27 and cost 9.3 s — to CoreText via `ctypes`, at 0.07 s.
  Import time fell from 9577 ms to 4 ms.
* Rotation is applied about the layer's real centre, found by pushing the local
  midpoint through `absoluteTransform`. Design tools rotate about the top-left
  corner, so `x + width/2` is correct only for unrotated layers.
* Server startup moved out of a view's `.task`: as an `LSUIElement` app there is
  no window at launch, so the bridge never began listening until someone opened
  the dashboard.
