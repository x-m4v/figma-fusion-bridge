> Historical macOS design notes. Some features described here are planned or experimental.
> For current setup and verified behavior, use [README](../README.md), [README.ru](../README.ru.md), and [VALIDATION](VALIDATION.md).

# Architecture

## The shape of it

```
┌─────────────────────┐
│  Figma plugin       │  controller (sandbox)  ─ reads the document
│  TypeScript         │  UI iframe             ─ the only half with network
└──────────┬──────────┘
           │  interchange JSON  +  assets by content hash
           ▼
┌─────────────────────┐
│  macOS bridge       │  Swift · BridgeCore library + menu-bar app
│  loopback only      │  pairing · transfer queue · asset cache
└──────────┬──────────┘
           │  HTTP long poll (stdlib only, so it works in Resolve's Python)
           ▼
┌─────────────────────┐
│  Resolve scripts    │  Python · fetch → validate → build → apply
│  FusionGraphBuilder │  pure: interchange JSON → Fusion ASCII
└──────────┬──────────┘
           ▼
     Fusion node graph
```

Four processes, three boundaries, one direction of dependency. The builder does
not know the network exists; the bridge does not know what a gradient is.

## The interchange format

`packages/schema` is the contract. It is versioned (`schemaVersion`), validated
at every boundary, and deliberately says nothing about Figma beyond
`source.app: "figma"`.

That neutrality is the point. The graph builder consumes *design documents*, not
Figma documents, so a Sketch or Illustrator producer is a sibling of
`packages/figma-plugin/src/extract.ts` rather than a rewrite of everything
downstream.

Two decisions inside the format are worth calling out.

**Nodes are a flat array with parent links,** not a nested tree. Hierarchy is
fully preserved by `parentId` + `childIndex`, and the flat form makes re-sync a
map lookup instead of a tree walk, lets a 1000-node payload validate
incrementally, and makes re-parenting between transfers representable.

**Paint opacity and layer opacity have separate homes and there is nowhere to
store their product.** Design tools treat them as different things — a 40% fill
inside a 70% layer is not a 28% fill, because layer opacity also scales the
stroke, the shadow and every sibling. Collapsing them is the most common way a
bridge silently alters a design, so the schema makes it unrepresentable.

## Why the graph builder emits text

Two ways exist to create Fusion nodes:

**Imperative** — `comp:AddTool(...)` then `tool:SetInput(...)` per input. Simple,
but one IPC round trip per call: a 150-layer frame is roughly 2000 of them. It
also cannot express structured values (`Gradient{}`, `Point{}`, `StyledText{}`)
cleanly from Python.

**Declarative** — generate the Fusion ASCII composition and hand the whole thing
over at once. One round trip regardless of size, structured values expressible
verbatim, and — decisively — **the generator becomes a pure function, testable
with no Resolve running at all.**

The builder takes the declarative path. `ffbridge/applier.py` then delivers the
result by the best mechanism the installed Resolve supports, detected by feature
probing rather than version numbers:

| Mode | How | When |
|---|---|---|
| `paste` | Hand Fusion the whole fragment | Preferred; full fidelity, one call |
| `api` | `AddTool` + `SetInput` per node | Always available; gradients degrade **with a warning** |
| `file` | Write the `.setting` and say where | Cannot fail; user drags it in |

The `.setting` file is written in every case, so the last resort is always
available even if a better path fails part way.

## Identity and re-sync

A Fusion node's link back to a design layer lives **in the node**, written with
`SetData`, and is never inferred from the node's name, position or order. All
three are things a motion designer legitimately changes; a bridge that reads
identity from them destroys work the first time someone renames a node.

Each design layer maps to a small fixed set of Fusion nodes with distinct roles:

```
design layer
  ├─ *_Shape    SOURCE   geometry — rebuilt from the design every sync
  ├─ *_Stroke   SOURCE   rebuilt
  ├─ *_Shadow   SOURCE   rebuilt
  ├─ *_Anim     USER     created once, never written to again
  └─ *_Merge    SPINE    reconnected; Blend and ApplyMode refreshed
```

`*_Anim` is the entire animation-preservation strategy. Keyframes go there, and
re-sync has no code path that touches it. A manifest under
`~/Library/Application Support/FigmaFusionBridge/Manifests` mirrors the same
mapping so the bridge can answer "what did this transfer create?" with Resolve
closed — but the per-node data is authoritative, because it cannot drift from
the node it describes.

## Graph layout

A graph that works but looks like spaghetti will not get animated, so layout is
part of the product. The scheme is a spine and ribs: the composite chain runs
left to right along one row, and each layer contributes a rib above it, built in
the order the pixels flow — shape, fill and stroke, effects, the user's
Transform, then down into the spine's Merge. Node names come from layer names
(`CTA Button` → `CTA_Button_Shape`, `CTA_Button_Stroke`, `CTA_Button_Anim`),
transliterated where needed so a Cyrillic or accented document does not become
`Layer_1 … Layer_N`.

## Transport

| Channel | Protocol | Why |
|---|---|---|
| Plugin → bridge | HTTP on `localhost` | The only network a Figma plugin iframe can reach. Figma's manifest rejects literal IP addresses, so the host name is required |
| Assets | HTTP `PUT`, content-addressed | Streams; base64 on a socket inflates binary by a third |
| Resolve ↔ bridge | HTTP long poll | Resolve's embedded Python has `urllib` and nothing else guaranteed |

The long poll is not a compromise. Assuming `websocket-client` is installed
inside DaVinci Resolve would make the tool fail on a stock install; `urllib` is
always there. Over loopback a long poll delivers as fast as a socket push and
costs nothing while idle.

## Security

* **Loopback only.** `NWParameters.requiredLocalEndpoint` pins the listener to
  the loopback interface — `127.0.0.1` and `::1`, both required explicitly.
  There is no code path that binds any other interface and no
  setting that exposes one.
* **Pairing.** Any web page the user has open can reach a loopback port, so the
  port is not a permission. The bridge shows a six-character code; the user
  types it into the plugin once; the plugin gets a token. Every endpoint that
  does anything requires that token. The code expires after ten minutes and is
  regenerated on every launch.
* **Constant-time comparison** on both code and token — the code is short enough
  that a timing oracle would meaningfully narrow the search space.
* **`session.json` is mode `0600`.** It carries the token the Resolve scripts
  use, and those scripts run as the user, so they need no pairing step.
* **Content verification.** Every uploaded asset is hashed and rejected if it
  does not match the id it arrived under; otherwise a truncated upload would be
  cached as though correct and served to every later transfer.
* **Schema validation** before anything reaches the builder.

Verified on a running instance: `/api/status` without a token returns 401, a
wrong pairing code returns 403 and is logged, and `lsof` shows the listener
bound to `127.0.0.1:8787` and `[::1]:8787` only.

Both loopback families are bound because Figma's `allowedDomains` accepts only
host names, and `localhost` resolves to both — with Chromium free to try the
IPv6 address first. Binding IPv4 alone works from `curl`, which falls back, and
fails intermittently from the plugin, which may not.

## Building without Xcode

The Swift package builds against the Command Line Tools, which changes two
things and is worth knowing before editing the app:

* **`@State` is a macro** in current SDKs, and macro plugins ship with Xcode.
  The app uses only non-macro property wrappers — `@StateObject`,
  `@ObservedObject`, `@Published`, `@Environment`. View-local state lives on
  `AppState`.
* **XCTest ships with Xcode too.** The Swift tests are therefore a plain
  executable target that links `BridgeCore` and exits non-zero on failure. It
  runs anywhere Swift does, including CI images with no Xcode.

Splitting `BridgeCore` out of the app was what made the second point possible,
and it is better structure regardless: the server, stores and installer have
nothing to do with SwiftUI, and now that boundary is enforced by the compiler.
`BridgeServer` talks to the UI through a `BridgeStatusSink` protocol rather than
holding the view model.

`scripts/build-app.sh` assembles the `.app` — a directory, an `Info.plist` with
`LSUIElement`, the Resolve payload in `Resources`, and an ad-hoc signature.
