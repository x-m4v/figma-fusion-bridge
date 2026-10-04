"""Applying a built graph to a live Fusion composition.

This is the only module that talks to Fusion, and it is deliberately thin.

Three delivery mechanisms are supported, tried in order of fidelity:

``paste``
    Hand Fusion the whole composition fragment in one operation. Structured
    values — gradients with per-stop alpha, points, styled text — arrive exactly
    as written, and a 150-layer frame is a single call rather than ~2000.

``api``
    Create tools with ``AddTool`` and set inputs one at a time. Always
    available, but cannot express a ``Gradient`` value, so gradients degrade to
    their first stop and say so.

``file``
    Write the ``.setting`` file and tell the user where it is. This one cannot
    fail, and it means a bridge that cannot reach Fusion still produces
    something the user can drag into the node graph by hand.

The file is written in every case, so ``file`` is always available as a
fallback even when a more capable path was attempted and failed part-way.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .ascii_writer import CompDocument, FuID, Gradient, Link, Point, Vec
from .builder import BuildResult
from .diagnostics import DiagnosticSink
from .identity import DATA_NAMESPACE, TransferManifest
from .paths import ensure_dirs, transfers_dir

MODE_PASTE = "paste"
MODE_API = "api"
MODE_FILE = "file"


@dataclass
class ApplyResult:
    mode: str
    created: List[str] = field(default_factory=list)
    setting_path: str = ""
    duration_ms: int = 0
    diagnostics: DiagnosticSink = field(default_factory=DiagnosticSink)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def write_setting_file(result: BuildResult, transfer_id: str) -> str:
    """Persist the composition fragment next to the transfer log."""
    ensure_dirs()
    safe = "".join(c for c in (transfer_id or "transfer") if c.isalnum() or c in "-_")
    path = os.path.join(transfers_dir(), f"{safe or 'transfer'}.setting")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(result.comp.render())
    return path


def _python_value(value: Any) -> Any:
    """Best-effort conversion of a writer value for ``SetInput``.

    Returns ``None`` when the value has no scalar equivalent, which is the
    caller's signal to record a fidelity warning rather than write something
    wrong.
    """
    if isinstance(value, FuID):
        return value.value
    if isinstance(value, Point):
        return {"__point__": (value.x, value.y)}
    if isinstance(value, Vec):
        return list(value.values)
    if isinstance(value, (int, float, str, bool)):
        return value
    return None


class FusionApplier:
    """Puts a built graph into a composition.

    ``comp`` is Fusion's composition object, obtained by the calling script from
    ``resolve.Fusion().GetCurrentComp()``. It is passed in rather than looked up
    here so this class can be exercised in tests with a stand-in object.
    """

    def __init__(self, comp: Any, fusion: Any = None) -> None:
        self.comp = comp
        self.fusion = fusion

    # -- capability detection ---------------------------------------------

    def detect_mode(self) -> str:
        """Work out the best available delivery mechanism for this install.

        Detection is by feature probing, not by version number: Resolve's
        scripting surface differs between builds and editions, and a version
        check would be a guess where a probe is a fact.
        """
        if self.comp is None:
            return MODE_FILE
        if hasattr(self.comp, "Paste") and hasattr(self.comp, "Lock"):
            return MODE_PASTE
        if hasattr(self.comp, "AddTool"):
            return MODE_API
        return MODE_FILE

    # -- application -------------------------------------------------------

    def apply(self, result: BuildResult, transfer_id: str, mode: Optional[str] = None) -> ApplyResult:
        started = time.time()
        path = write_setting_file(result, transfer_id)
        chosen = mode or self.detect_mode()
        out = ApplyResult(mode=chosen, setting_path=path)

        if chosen == MODE_FILE:
            out.diagnostics.warn(
                "MANUAL_IMPORT_REQUIRED",
                "Fusion could not be driven directly, so the composition was "
                "written to a file. Drag it into the Fusion node graph to import it.",
                detail=path,
            )
            out.duration_ms = int((time.time() - started) * 1000)
            return out

        # One undo step for the whole import, and no viewer refresh per node.
        self._begin()
        try:
            if chosen == MODE_PASTE:
                ok = self._apply_paste(path, out)
                if not ok:
                    out.diagnostics.info(
                        "FELL_BACK_TO_API",
                        "The fast import path was unavailable, so the graph was "
                        "built node by node instead.",
                    )
                    out.mode = MODE_API
                    self._apply_api(result, out)
            else:
                self._apply_api(result, out)
        finally:
            self._end()

        self._write_metadata(result.manifest, out)
        out.duration_ms = int((time.time() - started) * 1000)
        return out

    # -- mechanics ---------------------------------------------------------

    def _begin(self) -> None:
        for method, args in (("Lock", ()), ("StartUndo", ("Figma Fusion Bridge import",))):
            fn = getattr(self.comp, method, None)
            if callable(fn):
                try:
                    fn(*args)
                except Exception:
                    pass

    def _end(self) -> None:
        for method, args in (("EndUndo", (True,)), ("Unlock", ())):
            fn = getattr(self.comp, method, None)
            if callable(fn):
                try:
                    fn(*args)
                except Exception:
                    pass

    def _apply_paste(self, setting_path: str, out: ApplyResult) -> bool:
        """Hand the whole fragment to Fusion at once."""
        paste = getattr(self.comp, "Paste", None)
        if not callable(paste):
            return False
        try:
            with open(setting_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            return bool(paste(text))
        except Exception as exc:
            out.diagnostics.info(
                "PASTE_UNAVAILABLE",
                "The fast import path was not accepted by this version of Fusion.",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return False

    def _apply_api(self, result: BuildResult, out: ApplyResult) -> None:
        """Create the graph one tool at a time.

        Two passes: every tool is created first, then inputs are wired. A single
        pass would fail on any link that points forward, and forward links are
        normal in a fragment where merges are emitted before their inputs.
        """
        created: Dict[str, Any] = {}

        for tool in result.comp.tools:
            try:
                node = self.comp.AddTool(tool.tool_id, int(tool.pos[0]), int(tool.pos[1]))
            except Exception as exc:
                out.diagnostics.error(
                    "TOOL_CREATE_FAILED",
                    f'Could not create the "{tool.tool_id}" node for "{tool.name}".',
                    detail=f"{type(exc).__name__}: {exc}",
                )
                continue
            if node is None:
                out.diagnostics.error(
                    "TOOL_UNAVAILABLE",
                    f'This version of Fusion has no "{tool.tool_id}" node, so '
                    f'"{tool.name}" was skipped.',
                )
                continue
            try:
                node.SetAttrs({"TOOLS_Name": tool.name})
                if tool.comments:
                    node.SetAttrs({"TOOLS_Comments": tool.comments})
            except Exception:
                pass
            created[tool.name] = node
            out.created.append(tool.name)

        for tool in result.comp.tools:
            node = created.get(tool.name)
            if node is None:
                continue
            for key, value in tool.inputs.items():
                try:
                    if isinstance(value, Link):
                        source = created.get(value.source_op)
                        if source is not None:
                            node.ConnectInput(key, source)
                        continue
                    if isinstance(value, Gradient):
                        # No scalar form exists. Use the first stop so the layer
                        # is visible and the right colour family, and say so.
                        first = sorted(value.stops)[0][1]
                        node.SetInput("Type", "Solid")
                        node.SetInput("TopLeftRed", first[0])
                        node.SetInput("TopLeftGreen", first[1])
                        node.SetInput("TopLeftBlue", first[2])
                        node.SetInput("TopLeftAlpha", first[3])
                        out.diagnostics.warn(
                            "GRADIENT_DEGRADED",
                            f'The gradient on "{tool.name}" could not be created '
                            "through this import path and was replaced with its "
                            "first colour. Use the .setting file to get the full gradient.",
                            detail=out.setting_path,
                        )
                        continue
                    converted = _python_value(value)
                    if converted is None:
                        continue
                    if isinstance(converted, dict) and "__point__" in converted:
                        x, y = converted["__point__"]
                        node.SetInput(key, {1: x, 2: y})
                        continue
                    node.SetInput(key, converted)
                except Exception as exc:
                    out.diagnostics.warn(
                        "INPUT_NOT_SET",
                        f'One setting on "{tool.name}" could not be applied.',
                        detail=f"{key}: {type(exc).__name__}: {exc}",
                    )

    def _write_metadata(self, manifest: TransferManifest, out: ApplyResult) -> None:
        """Stamp identity onto the created nodes so re-sync can find them again.

        The ASCII path already carries this in ``CustomData``; writing it again
        through ``SetData`` costs one call per node and guarantees the data is
        present whichever path was taken.
        """
        find = getattr(self.comp, "FindTool", None)
        if not callable(find):
            return
        for node_id, parts in manifest.nodes.items():
            for part, tool_name in parts.items():
                try:
                    tool = find(tool_name)
                    if tool is None:
                        continue
                    tool.SetData(f"{DATA_NAMESPACE}.nodeId", node_id)
                    tool.SetData(f"{DATA_NAMESPACE}.part", part)
                    tool.SetData(f"{DATA_NAMESPACE}.transferId", manifest.transfer_id)
                    tool.SetData(f"{DATA_NAMESPACE}.documentId", manifest.document_id)
                except Exception:
                    # Metadata is important but not worth aborting an import for.
                    pass


def find_existing_nodes(comp: Any) -> Dict[str, Dict[str, Any]]:
    """Index a composition's existing bridge-created nodes by design layer id.

    Used by re-sync. Reads identity from node data only — never from names or
    positions, both of which the user is free to change.
    """
    index: Dict[str, Dict[str, Any]] = {}
    get_list = getattr(comp, "GetToolList", None)
    if not callable(get_list):
        return index
    try:
        tools = get_list(False) or {}
    except Exception:
        return index

    for tool in (tools.values() if hasattr(tools, "values") else tools):
        try:
            node_id = tool.GetData(f"{DATA_NAMESPACE}.nodeId")
            part = tool.GetData(f"{DATA_NAMESPACE}.part")
        except Exception:
            continue
        if node_id and part:
            index.setdefault(str(node_id), {})[str(part)] = tool
    return index
