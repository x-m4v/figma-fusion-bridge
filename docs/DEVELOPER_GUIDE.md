> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Developer guide

## Layout

```
packages/schema/          Interchange format — the contract. TypeScript + Zod
packages/figma-plugin/    Controller, extractor, UI, transport
bridge-macos/
  Sources/BridgeCore/     Server, session, stores, installer — no SwiftUI
  Sources/FigmaFusionBridge/  Menu-bar app
  Sources/BridgeTests/    Test executable (see "Testing")
resolve/ffbridge/         FusionGraphBuilder and friends — pure Python
resolve/scripts/          What appears under Workspace ▸ Scripts
resolve/tests/            pytest suite
scripts/                  build-app.sh, build-manual.py
```

## Getting set up

```bash
npm install
make build
make test
```

You need Node 20+, Python 3.9+, Swift 5.9+. **You do not need Xcode** — see
below for what that costs.

## The rules that shape the code

**Verify API surface, never assume it.** Every Fusion node id and input name in
the builder was read out of composition files shipped by Blackmagic Design, or
out of the Fusion libraries themselves — not from memory. Two examples of why:
the drop-shadow node is `Shadow`, not `DropShadow`; and Fusion's blend-mode
identifiers are inconsistently spaced (`"Color Burn"` but `"LinearBurn"`,
`"Soft Light"` but `"LighterColor"`). An unrecognised identifier is silently
ignored by Fusion, so a wrong guess produces no error anywhere — just a wrong
picture. `docs/FEASIBILITY.md` records what was verified and how.

**Nothing degrades silently.** Every fallback path in the builder takes a
diagnostic argument. If you add a case where the output does not match the
design, emit a warning naming the layer, and add a row to `LIMITATIONS.md`.

**The builder stays pure.** `resolve/ffbridge/builder.py` and everything it
imports must not touch the network, the filesystem or Resolve. That is what lets
244 tests cover the conversion maths without launching anything.

## Testing

```bash
make test          # everything
make test-python   # builder, 244 tests
make test-swift    # bridge, 44 tests
```

The Python suite covers coordinate mapping at seven resolutions, gradient
transform decomposition at 0°/45°/90°/180° and awkward angles, stroke alignment
geometry, the exact sRGB transfer function, blend-mode mapping, node naming
including transliteration, re-sync planning, and the builder end to end.

### Why the Swift tests are not XCTest

XCTest ships with Xcode, not the Command Line Tools. Rather than have a suite
that cannot run on a clean machine or a CI image without Xcode, `BridgeTests` is
an ordinary executable target: it links `BridgeCore`, asserts, prints, and exits
non-zero on failure.

Splitting `BridgeCore` out of the app is what made that possible, and it is
better structure anyway — the networking and storage layers have no business
knowing about SwiftUI. `BridgeServer` reaches the interface through the
`BridgeStatusSink` protocol rather than holding the view model.

### The other Xcode constraint

`@State` is a compiler macro in current SDKs, and macro plugins ship with Xcode.
**Do not add `@State`, `@Observable` or `@Bindable`** to the app target or it
will stop building on a CLT-only machine. Use `@StateObject`, `@ObservedObject`,
`@Published` and `@Environment`, and keep view-local state on `AppState`.

## Adding a Fusion node type

1. Confirm the registry id exists:
   ```bash
   strings -a "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/libfusionoperators.dylib" | grep -x 'sStar'
   ```
2. Confirm the input names against real content:
   ```bash
   unzip -o "/Library/Application Support/Blackmagic Design/Fusion/Templates.drfx" -d /tmp/drfx
   grep -rh -A 20 "= sStar {" /tmp/drfx | grep -oE "[A-Za-z0-9_.]+ = Input" | sort -u
   ```
3. Add the mapping in `builder.py`, with a test in `resolve/tests/test_builder.py`.
4. If it cannot be exact, emit a diagnostic and add a `LIMITATIONS.md` row.

## Adding a producer (Sketch, Illustrator, SVG)

Write something that emits a valid `InterchangeDocument`. Do not touch the
builder. `packages/schema/src/document.ts` is the contract, and
`validateReferentialIntegrity` will tell you what is inconsistent.

## Changing the schema

* Additive change → bump the **minor**. Older consumers ignore unknown fields.
* Breaking change → bump the **major** and add a migration.
  `checkCompatibility()` in `packages/schema/src/version.ts` decides what a
  reader does, and returns a reason the UI can show rather than a boolean.

## The bridge HTTP API

Unauthenticated:

| | |
|---|---|
| `GET /api/hello` | Handshake. Says nothing about the user's work |
| `POST /api/pair` | `{code}` → `{token}` |

Everything else needs `X-FFBridge-Token`:

| | |
|---|---|
| `GET /api/status` | Connection state |
| `POST /api/transfer` | Submit a document |
| `GET /api/transfer/latest` | Fetch the pending transfer |
| `GET /api/transfer/wait?timeout=30` | Long poll |
| `POST /api/transfer/report` | Report an import result |
| `POST /api/asset/known` | `{ids}` → `{known}`; skips re-uploads |
| `PUT /api/asset/{sha256}` | Upload; rejected if the bytes do not match |
| `GET /api/asset/{sha256}` | Download |

## Release

```bash
make test && make build && make pdf
```

`scripts/build-app.sh` assembles `dist/Figma Fusion Bridge.app` and ad-hoc signs
it. Replace the `codesign` identity for distribution and add notarisation.
