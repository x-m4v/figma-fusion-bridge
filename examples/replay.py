#!/usr/bin/env python3
"""Replay an interchange document into a Fusion composition, with no Resolve.

Useful for three things: reproducing a user's bug report from the JSON they
attached, checking the effect of a builder change on a real design, and trying
the tool before installing anything.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resolve"))

from ffbridge.assets import AssetCache               # noqa: E402
from ffbridge.builder import BuildOptions, FusionGraphBuilder  # noqa: E402
from ffbridge.fonts import FontResolver, system_font_catalogue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", help="an interchange JSON file")
    parser.add_argument("-o", "--output", help="where to write the .setting file")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--colour", default="MATCH_SRGB",
                        choices=["MATCH_SRGB", "PROJECT_MANAGED"])
    args = parser.parse_args()

    with open(args.document, "r", encoding="utf-8") as fh:
        document = json.load(fh)

    options = BuildOptions(
        comp_width=args.width,
        comp_height=args.height,
        color_policy=args.colour,
        asset_paths=AssetCache().resolve_paths(document.get("assets", [])),
    )
    result = FusionGraphBuilder(
        document, options, FontResolver(system_font_catalogue())
    ).build()

    out = args.output or os.path.splitext(args.document)[0] + ".setting"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(result.comp.render())

    rule = "─" * 58
    print(f"\n{rule}\n  Replayed {os.path.basename(args.document)}\n{rule}")
    print(f"  {result.node_count} nodes · {args.width}x{args.height}")
    print(f"  Wrote {out}\n")
    for diagnostic in result.diagnostics.sorted():
        print("  " + diagnostic.format_line())
    print(f"\n  {result.diagnostics.error_count} error(s), "
          f"{result.diagnostics.warning_count} warning(s)\n{rule}\n")
    return 1 if result.diagnostics.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
