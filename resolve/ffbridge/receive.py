"""The Receive workflow, shared by every menu command.

Order of operations matters here and is deliberate:

    fetch document -> validate schema -> fetch missing assets -> build graph
    -> validate graph -> touch the composition

The composition is the last thing touched. Everything that can fail — network,
schema mismatch, a missing image, an unbuildable layer — has already failed by
then, so a broken transfer leaves the user's work exactly as it was rather than
half-importing and stopping at layer 87 of 100.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from . import SCHEMA_VERSION, __version__
from .applier import FusionApplier, find_existing_nodes
from .assets import AssetCache
from .builder import BuildOptions, FusionGraphBuilder
from .client import BridgeClient, BridgeError
from .diagnostics import DiagnosticSink
from .fonts import FontResolver, system_font_catalogue
from .identity import TransferManifest, plan_sync
from .logging_setup import get_logger
from .paths import ensure_dirs, manifests_dir

log = get_logger("receive")


# ---------------------------------------------------------------------------
# Schema compatibility
# ---------------------------------------------------------------------------

SUPPORTED_MAJOR = 1


def check_schema(document: Dict[str, Any]) -> Optional[str]:
    """Return an error message if this build cannot read the document."""
    version = str(document.get("schemaVersion", ""))
    parts = version.split(".")
    try:
        major = int(parts[0])
    except (ValueError, IndexError):
        return (
            f'This transfer has an unreadable format version ("{version}"). '
            "Update the Figma plugin and the bridge to matching versions."
        )
    if major != SUPPORTED_MAJOR:
        return (
            f"This transfer uses format version {version}, but this version of "
            f"the Resolve scripts reads version {SCHEMA_VERSION}. "
            "Update whichever component is older."
        )
    return None


# ---------------------------------------------------------------------------
# Composition helpers
# ---------------------------------------------------------------------------

def _comp_resolution(comp: Any, fallback: Tuple[int, int] = (1920, 1080)) -> Tuple[int, int]:
    """Read the composition's frame format.

    Falls back rather than raising: an unusual project setup should not stop an
    import, and a wrong-but-sane resolution is recoverable by the user where a
    failed import is just an error message.
    """
    if comp is None:
        return fallback
    try:
        attrs = comp.GetAttrs() or {}
        w = int(attrs.get("COMPN_ImageWidth") or 0)
        h = int(attrs.get("COMPN_ImageHeight") or 0)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    try:
        w = int(comp.GetPrefs("Comp.FrameFormat.Width") or 0)
        h = int(comp.GetPrefs("Comp.FrameFormat.Height") or 0)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return fallback


def _get_comp(fusion: Any, resolve: Any, into_current: bool, diag: DiagnosticSink) -> Any:
    if fusion is None:
        diag.error(
            "NO_FUSION",
            "Fusion is not available. Run this from the Fusion page in DaVinci Resolve.",
        )
        return None

    comp = None
    try:
        comp = fusion.GetCurrentComp()
    except Exception as exc:
        diag.error(
            "NO_COMPOSITION",
            "There is no open Fusion composition. Open a clip on the Fusion page "
            "and run this again.",
            detail=str(exc),
        )
        return None

    if comp is None:
        diag.error(
            "NO_COMPOSITION",
            "There is no open Fusion composition. Open a clip on the Fusion page "
            "and run this again.",
        )
    return comp


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def _ensure_assets(
    client: Optional[BridgeClient], document: Dict[str, Any], diag: DiagnosticSink
) -> Dict[str, str]:
    cache = AssetCache()
    assets = document.get("assets") or []
    paths = cache.resolve_paths(assets)

    missing = [a for a in assets if str(a.get("id")) not in paths]
    if missing and client is None:
        for a in missing:
            diag.error(
                "ASSET_MISSING",
                f'The image "{a.get("suggestedName") or a.get("id")}" is not '
                "available and could not be downloaded.",
            )
        return paths

    for a in missing:
        asset_id = str(a.get("id"))
        try:
            data = client.fetch_asset(asset_id)
            stored = cache.store(
                data,
                str(a.get("mimeType", "")),
                str(a.get("suggestedName", "")),
                str(a.get("sha256", "")),
            )
            paths[asset_id] = stored.path
        except (BridgeError, ValueError, OSError) as exc:
            diag.error(
                "ASSET_DOWNLOAD_FAILED",
                f'The image "{a.get("suggestedName") or asset_id}" could not be '
                "downloaded from the bridge.",
                detail=str(exc),
            )
    return paths


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

def _manifest_path(document_id: str, comp_key: str) -> str:
    safe_doc = "".join(c for c in document_id if c.isalnum() or c in "-_") or "doc"
    safe_comp = "".join(c for c in comp_key if c.isalnum() or c in "-_") or "comp"
    return os.path.join(manifests_dir(), f"{safe_doc}__{safe_comp}.json")


def _load_manifest(path: str) -> Optional[TransferManifest]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return TransferManifest.from_dict(json.load(fh))
    except (ValueError, OSError):
        return None


def _save_manifest(path: str, manifest: TransferManifest) -> None:
    ensure_dirs()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, indent=2)
    except OSError as exc:
        log.warning("Could not write manifest %s: %s", path, exc)


def _comp_key(comp: Any) -> str:
    if comp is None:
        return "none"
    try:
        attrs = comp.GetAttrs() or {}
        return str(attrs.get("COMPS_Name") or attrs.get("COMPS_FileName") or "comp")
    except Exception:
        return "comp"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(
    title: str, diag: DiagnosticSink, node_count: int = 0,
    asset_count: int = 0, duration_ms: int = 0, extra: str = "",
) -> None:
    """Print a transfer log the user can actually read.

    Fusion's Console is the only output surface available from a script, so the
    report is plain text — but it is still a report, not a traceback. Technical
    detail is indented under its message so it can be skimmed past.
    """
    line = "─" * 58
    print(f"\n{line}\n  {title}\n{line}")
    if node_count or asset_count:
        print(f"  {node_count} nodes · {asset_count} assets · {duration_ms} ms")
    if extra:
        print(f"  {extra}")

    items = diag.sorted()
    if not items:
        print("  No warnings.")
    else:
        print("")
        for d in items:
            print("  " + d.format_line())
            if d.detail:
                print(f"      {d.detail}")

    errors, warnings = diag.error_count, diag.warning_count
    print("")
    print(f"  {errors} error(s), {warnings} warning(s)")
    print(line + "\n")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def receive(
    fusion: Any = None,
    resolve: Any = None,
    into_current: bool = True,
    pull: bool = False,
    document: Optional[Dict[str, Any]] = None,
) -> int:
    """Fetch, build and apply. Returns a process-style exit code."""
    started = time.time()
    diag = DiagnosticSink()
    ensure_dirs()

    # 1. Get the document.
    client: Optional[BridgeClient] = None
    if document is None:
        try:
            client = BridgeClient()
            document = client.request_selection() if pull else client.latest_transfer()
        except BridgeError as exc:
            diag.error("BRIDGE_UNAVAILABLE", exc.message, detail=exc.detail)
            _print_report("Figma Fusion Bridge — Receive failed", diag)
            return 1

    if not document:
        diag.warn(
            "NOTHING_TO_RECEIVE",
            "There is nothing waiting to be received. Select something in Figma "
            "and press Send to Fusion.",
        )
        _print_report("Figma Fusion Bridge — Nothing to receive", diag)
        return 0

    # 2. Validate the format before doing any work.
    schema_error = check_schema(document)
    if schema_error:
        diag.error("SCHEMA_INCOMPATIBLE", schema_error)
        _print_report("Figma Fusion Bridge — Incompatible transfer", diag)
        return 1

    _merge_producer_diagnostics(document, diag)

    # 3. Composition.
    comp = _get_comp(fusion, resolve, into_current, diag)
    if comp is None and fusion is not None:
        _print_report("Figma Fusion Bridge — Receive failed", diag)
        return 1

    comp_w, comp_h = _comp_resolution(comp)

    # 4. Assets.
    asset_paths = _ensure_assets(client, document, diag)

    # 5. Build — still nothing touched in the composition.
    options_in = document.get("options") or {}
    options = BuildOptions(
        comp_width=comp_w,
        comp_height=comp_h,
        color_policy=str(options_in.get("colorHandling", "MATCH_SRGB")),
        clip_frames=str(options_in.get("clipFrames", "AUTO")),
        vector_strategy=str(options_in.get("vectorStrategy", "AUTO")),
        include_hidden=bool(options_in.get("includeHidden", False)),
        asset_paths=asset_paths,
    )
    resolver = FontResolver(system_font_catalogue())
    result = FusionGraphBuilder(document, options, resolver).build()
    diag.extend(result.diagnostics)

    if diag.has_errors and not result.comp.tools:
        _print_report("Figma Fusion Bridge — Receive failed", diag)
        return 1

    # 6. Re-sync bookkeeping.
    document_id = str((document.get("source") or {}).get("documentId", ""))
    manifest_path = _manifest_path(document_id, _comp_key(comp))
    previous = _load_manifest(manifest_path)
    plan = plan_sync(previous, [str(n.get("id")) for n in document.get("nodes", [])])

    if previous is not None:
        diag.info(
            "RESYNC",
            f"{len(plan.updated)} layer(s) updated, {len(plan.created)} added, "
            f"{len(plan.removed)} no longer in the design.",
        )
        if plan.removed:
            diag.warn(
                "LAYERS_REMOVED_IN_DESIGN",
                f"{len(plan.removed)} layer(s) were deleted in Figma. Their Fusion "
                "nodes were kept so no animation is lost — delete them by hand if "
                "you no longer need them.",
            )
        existing = find_existing_nodes(comp)
        preserved = [nid for nid in plan.preserved_animation if nid in existing]
        if preserved:
            diag.info(
                "ANIMATION_PRESERVED",
                f"Animation on {len(preserved)} layer(s) was left untouched.",
            )

    # 7. Apply. This is the first thing that changes the user's composition.
    applier = FusionApplier(comp, fusion)
    applied = applier.apply(result, str(document.get("transferId", "")))
    diag.extend(applied.diagnostics)

    result.manifest.assets = asset_paths
    result.manifest.diagnostics = diag.to_list()
    _save_manifest(manifest_path, result.manifest)

    duration = int((time.time() - started) * 1000)
    _print_report(
        "Figma Fusion Bridge — Received",
        diag,
        node_count=result.node_count,
        asset_count=len(asset_paths),
        duration_ms=duration,
        extra=f"Import path: {applied.mode} · Composition: {comp_w}x{comp_h}",
    )

    if client is not None:
        client.report(
            str(document.get("transferId", "")),
            {
                "status": "error" if diag.has_errors else "ok",
                "nodeCount": result.node_count,
                "assetCount": len(asset_paths),
                "durationMs": duration,
                "diagnostics": diag.to_list(),
            },
        )
    return 1 if diag.has_errors else 0


def _merge_producer_diagnostics(document: Dict[str, Any], diag: DiagnosticSink) -> None:
    """Carry the plugin's own warnings into the Resolve-side report.

    The producer knows things the builder cannot — that a layer used an
    unsupported feature, for instance — and those warnings would otherwise be
    lost at the boundary.
    """
    from .diagnostics import Diagnostic

    for d in document.get("diagnostics") or []:
        diag.items.append(
            Diagnostic(
                severity=str(d.get("severity", "INFO")),
                code=str(d.get("code", "PRODUCER")),
                message=str(d.get("message", "")),
                node_id=d.get("nodeId"),
                node_name=d.get("nodeName"),
                detail=d.get("detail"),
            )
        )


def connection_test(fusion: Any = None, resolve: Any = None) -> int:
    """Check every link in the chain and say which one is broken."""
    diag = DiagnosticSink()
    print("\nFigma Fusion Bridge — Connection Test\n" + "─" * 58)

    print(f"  Scripts      version {__version__}, schema {SCHEMA_VERSION}")

    if resolve is not None:
        try:
            print(f"  Resolve      {resolve.GetProductName()} {resolve.GetVersionString()}")
        except Exception as exc:
            diag.warn("RESOLVE_VERSION", "Could not read the Resolve version.", detail=str(exc))
    else:
        diag.error("NO_RESOLVE", "This script was not run from inside DaVinci Resolve.")

    comp = None
    if fusion is not None:
        try:
            comp = fusion.GetCurrentComp()
        except Exception:
            comp = None
    if comp is not None:
        w, h = _comp_resolution(comp)
        mode = FusionApplier(comp, fusion).detect_mode()
        print(f"  Fusion       composition {w}x{h}, import path: {mode}")
    else:
        diag.warn(
            "NO_COMPOSITION",
            "No Fusion composition is open. Open one before receiving a design.",
        )

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
    except BridgeError as exc:
        diag.error("BRIDGE_UNAVAILABLE", exc.message, detail=exc.detail)

    cache = AssetCache()
    size_mb = cache.total_size() / (1024 * 1024)
    print(f"  Asset cache  {size_mb:.1f} MB")

    _print_report("Result", diag)
    return 1 if diag.has_errors else 0
