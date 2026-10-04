"""Command-line entry point, driven by the Lua menu commands.

Why this exists: DaVinci Resolve ships LuaJIT but no Python, so `.py` files in
the Scripts folder are only listed when a Python framework happens to be
installed in a system location. Lua is always available, so the menu commands
are Lua — and Lua shells out to this.

The split is a good one regardless. Everything here is pure Python with no
Resolve bindings: it talks to the bridge, converts the design and writes a
Fusion composition fragment to disk. The Lua half does the one thing only
Resolve can do, which is put those nodes into the open composition.

Output contract with the Lua caller: a human-readable report on stdout, then a
final line

    FFBRIDGE_RESULT <json>

carrying the setting file's path, counts and status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

from . import SCHEMA_VERSION, __version__
from .applier import write_setting_file
from .assets import AssetCache
from .builder import BuildOptions, FusionGraphBuilder
from .client import BridgeClient, BridgeError
from .diagnostics import DiagnosticSink
from .fonts import FontResolver, system_font_catalogue
from .identity import TransferManifest
from .paths import ensure_dirs, manifests_dir
from .safe_graph import prepare_receive_graph
from .color_pipeline import add_color_boundary
from .receive import _merge_producer_diagnostics, _print_report, check_schema

RESULT_PREFIX = "FFBRIDGE_RESULT "


def emit(result: Dict[str, Any]) -> None:
    """Write the machine-readable line the Lua side parses."""
    sys.stdout.write(RESULT_PREFIX + json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def cmd_test(args: argparse.Namespace) -> int:
    diag = DiagnosticSink()
    print("\nFigma Fusion Bridge — Connection Test\n" + "─" * 58)
    print(f"  Scripts      version {__version__}, schema {SCHEMA_VERSION}")
    print(f"  Python       {sys.version.split()[0]} at {sys.executable}")
    if args.width and args.height:
        print(f"  Composition  {args.width}x{args.height}")

    ok = True
    try:
        client = BridgeClient()
        status = client.status()
        print(f"  Bridge       connected on port {client.session.port}")
        if status.get("figmaConnected"):
            print("  Figma        plugin connected")
        else:
            diag.warn(
                "FIGMA_DISCONNECTED",
                "The Figma plugin is not connected. Open the plugin in Figma.",
            )
        pending = client.latest_transfer()
        if pending:
            print(f"  Pending      1 transfer waiting ({len(pending.get('nodes', []))} layers)")
        else:
            print("  Pending      nothing waiting")
    except BridgeError as exc:
        diag.error("BRIDGE_UNAVAILABLE", exc.message, detail=exc.detail)
        ok = False

    cache = AssetCache()
    print(f"  Asset cache  {cache.total_size() / (1024 * 1024):.1f} MB")

    _print_report("Result", diag)
    emit({"status": "ok" if ok and not diag.has_errors else "error",
          "errors": diag.error_count, "warnings": diag.warning_count})
    return 0 if ok and not diag.has_errors else 1


def cmd_build(args: argparse.Namespace) -> int:
    """Fetch a transfer and turn it into a Fusion composition fragment."""
    started = time.time()
    diag = DiagnosticSink()
    ensure_dirs()

    try:
        client: Optional[BridgeClient] = BridgeClient()
        document = client.request_selection() if args.pull else client.latest_transfer()
    except BridgeError as exc:
        diag.error("BRIDGE_UNAVAILABLE", exc.message, detail=exc.detail)
        _print_report("Figma Fusion Bridge — Receive failed", diag)
        emit({"status": "error", "message": exc.message})
        return 1

    if not document:
        diag.warn(
            "NOTHING_TO_RECEIVE",
            "There is nothing waiting to be received. Select something in Figma "
            "and press Send to Fusion.",
        )
        _print_report("Figma Fusion Bridge — Nothing to receive", diag)
        emit({"status": "empty"})
        return 0

    schema_error = check_schema(document)
    if schema_error:
        diag.error("SCHEMA_INCOMPATIBLE", schema_error)
        _print_report("Figma Fusion Bridge — Incompatible transfer", diag)
        emit({"status": "error", "message": schema_error})
        return 1

    _merge_producer_diagnostics(document, diag)

    # Assets first: a missing image should fail before anything is built.
    cache = AssetCache()
    asset_paths = cache.resolve_paths(document.get("assets") or [])
    for asset in document.get("assets") or []:
        asset_id = str(asset.get("id"))
        if asset_id in asset_paths:
            continue
        try:
            data = client.fetch_asset(asset_id)
            stored = cache.store(data, str(asset.get("mimeType", "")),
                                 str(asset.get("suggestedName", "")),
                                 str(asset.get("sha256", "")))
            asset_paths[asset_id] = stored.path
        except (BridgeError, ValueError, OSError) as exc:
            diag.error(
                "ASSET_DOWNLOAD_FAILED",
                f'The image "{asset.get("suggestedName") or asset_id}" could not be downloaded.',
                detail=str(exc),
            )

    options_in = document.get("options") or {}
    options = BuildOptions(
        comp_width=args.width,
        comp_height=args.height,
        # Keep source values encoded; perform conversion once at the boundary.
        color_policy="MATCH_SRGB",
        clip_frames=str(options_in.get("clipFrames", "AUTO")),
        vector_strategy=str(options_in.get("vectorStrategy", "AUTO")),
        include_hidden=bool(options_in.get("includeHidden", False)),
        asset_paths=asset_paths,
    )
    result = FusionGraphBuilder(
        document, options, FontResolver(system_font_catalogue())
    ).build()
    prepare_receive_graph(result, args.width, args.height)
    add_color_boundary(result, args.fusion_color_space)
    from .organize import organize_result
    organize_result(result)
    diag.extend(result.diagnostics)

    if diag.has_errors:
        _print_report("Figma Fusion Bridge — Import blocked", diag)
        emit({"status": "error", "errors": diag.error_count})
        return 1

    transfer_id = str(document.get("transferId", "transfer"))
    setting_path = write_setting_file(result, transfer_id)

    result.manifest.assets = asset_paths
    result.manifest.diagnostics = diag.to_list()
    _save_manifest(result.manifest)

    duration = int((time.time() - started) * 1000)
    _print_report(
        "Figma Fusion Bridge — Ready to place",
        diag,
        node_count=result.node_count,
        asset_count=len(asset_paths),
        duration_ms=duration,
        extra=f"Composition: {args.width}x{args.height}",
    )

    try:
        client.report(transfer_id, {
            "status": "prepared",
            "nodeCount": result.node_count,
            "assetCount": len(asset_paths),
            "durationMs": duration,
            "diagnostics": diag.to_list(),
        })
    except Exception:
        pass

    emit({
        "status": "error" if diag.has_errors else "ok",
        "setting": setting_path,
        "outputTool": result.output_tool,
        "fusionColorSpace": args.fusion_color_space,
        "nodes": result.node_count,
        "assets": len(asset_paths),
        "warnings": diag.warning_count,
        "errors": diag.error_count,
        "durationMs": duration,
        "transferId": transfer_id,
    })
    return 1 if diag.has_errors else 0


def _save_manifest(manifest: TransferManifest) -> None:
    safe = "".join(c for c in manifest.document_id if c.isalnum() or c in "-_") or "doc"
    path = os.path.join(manifests_dir(), f"{safe}.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, indent=2)
    except OSError:
        pass


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="ffbridge")
    sub = parser.add_subparsers(dest="command", required=True)

    p_test = sub.add_parser("test", help="check the connection")
    p_test.add_argument("--width", type=int, default=0)
    p_test.add_argument("--height", type=int, default=0)
    p_test.set_defaults(func=cmd_test)

    p_build = sub.add_parser("build", help="fetch a transfer and build a composition")
    p_build.add_argument("--width", type=int, required=True)
    p_build.add_argument("--height", type=int, required=True)
    p_build.add_argument("--fusion-color-space", default="UNKNOWN",
                         choices=("UNKNOWN", "UNMANAGED", "DWG_LINEAR", "SRGB_LINEAR"))
    p_build.add_argument("--pull", action="store_true",
                         help="ask Figma for the current selection instead of the queue")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
