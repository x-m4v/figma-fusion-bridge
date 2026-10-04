# Examples

## `sample-transfer.json`

A complete interchange document, produced by the plugin from a small UI design:
a gradient-filled button with an inside stroke, a drop shadow, a clipping frame,
`Text+` content and an image fill.

It is the fastest way to exercise the whole Resolve side without Figma running:

```bash
# Build a Fusion composition from it, with no Resolve involved
python3 examples/replay.py examples/sample-transfer.json
```

That writes a `.setting` file you can drag straight into the Fusion node graph,
and prints the same transfer report Resolve would.

## Building the example Figma document

`figma-test-document.md` lists the layers to create for a coverage test — one of
every supported and every unsupported case, so a single Send exercises every
path in the builder and every diagnostic it can emit.
