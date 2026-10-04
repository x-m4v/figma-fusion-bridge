"""FusionGraphBuilder — interchange document to Fusion node graph.

This module knows nothing about Figma, nothing about the network and nothing
about Resolve. It takes a parsed interchange document and returns Fusion ASCII.
That isolation is what makes the conversion testable, and it is also what lets a
Sketch or Illustrator producer be added later without touching any of this.

Shape units, derived from composition files shipped by Blackmagic Design:

* ``s*`` shape tools work in a canvas whose unit is the composition **height**,
  origin at the centre. ``Width``/``Height`` are full extents in that unit.
* ``CornerRadius`` on a shape is **normalised against half the shorter side**,
  so 0 is square and 1 is fully rounded. Shipped content shows
  ``CornerRadius = 1`` on a shape 0.022 x 0.05 units, which is only meaningful
  under that reading.
* ``BorderWidth`` is a length in shape units, and ``Solid = 0`` switches a shape
  from filled to outlined — which is what makes a stroke a first-class branch
  rather than a second shape subtracted from the first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import SCHEMA_VERSION, __version__
from .ascii_writer import CompDocument, FuID, Gradient, Link, Point, Tool, Vec
from .blend import map_blend_mode
from .color import convert_rgba, multiply_alpha
from .coordinate import CoordinateMapper, decompose, mat_apply, mapper_for
from .diagnostics import DiagnosticSink
from .effects import (
    blur_radius_to_fusion_size,
    background_blur_support_note,
    drop_shadow_params,
    inner_shadow_plan,
)
from .fonts import FontResolver, MISSING, EXACT
from .gradient import build_stops, geometry_from_handles, geometry_from_transform, map_gradient_type
from .identity import (
    NodeIdentity,
    ROLE_CONTAINER,
    ROLE_SOURCE,
    ROLE_SPINE,
    ROLE_USER,
    TransferManifest,
)
from .layout import GraphLayout
from .naming import NameAllocator

SHAPE_KINDS = {"RECTANGLE", "ELLIPSE", "POLYGON", "STAR", "LINE", "VECTOR", "BOOLEAN_OPERATION"}
CONTAINER_KINDS = {"FRAME", "GROUP", "COMPONENT", "COMPONENT_SET", "INSTANCE", "SECTION"}


@dataclass
class BuildOptions:
    comp_width: int = 1920
    comp_height: int = 1080
    color_policy: str = "MATCH_SRGB"
    clip_frames: str = "AUTO"          # AUTO | ON | OFF
    vector_strategy: str = "AUTO"      # NATIVE | AUTO | RASTER
    include_hidden: bool = False
    fit_to_comp: bool = False
    #: Absolute paths for assets, keyed by asset id. Filled by the applier.
    asset_paths: Dict[str, str] = field(default_factory=dict)


@dataclass
class BuildResult:
    comp: CompDocument
    manifest: TransferManifest
    diagnostics: DiagnosticSink
    #: Fusion tool name of the final composite, for connecting to a MediaOut.
    output_tool: Optional[str] = None

    @property
    def node_count(self) -> int:
        return len(self.comp)


@dataclass
class _Branch:
    """A built layer: the tool that produces its image, plus its bookkeeping."""

    tool_name: str
    node_id: str
    opacity: float = 1.0
    blend_mode: str = "NORMAL"
    is_mask: bool = False


class FusionGraphBuilder:
    """Converts one interchange document into one Fusion composition."""

    def __init__(
        self,
        document: Dict[str, Any],
        options: Optional[BuildOptions] = None,
        font_resolver: Optional[FontResolver] = None,
    ) -> None:
        self.doc = document
        self.opt = options or BuildOptions()
        self.diag = DiagnosticSink()
        self.comp = CompDocument()
        self.names = NameAllocator()
        self.layout = GraphLayout()
        self.fonts = font_resolver or FontResolver({})

        canvas = (document.get("canvas") or {}).get("frame") or {}
        self.mapper: CoordinateMapper = mapper_for(
            self.opt.comp_width,
            self.opt.comp_height,
            float(canvas.get("x", 0.0)),
            float(canvas.get("y", 0.0)),
            float(canvas.get("width", 0.0)),
            float(canvas.get("height", 0.0)),
            fit=self.opt.fit_to_comp,
        )

        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._children: Dict[Optional[str], List[Dict[str, Any]]] = {}
        self._index_nodes()

        self.manifest = TransferManifest(
            transfer_id=str(document.get("transferId", "")),
            document_id=str((document.get("source") or {}).get("documentId", "")),
            schema_version=str(document.get("schemaVersion", SCHEMA_VERSION)),
            created_at=str(document.get("createdAt", "")),
            comp_width=self.opt.comp_width,
            comp_height=self.opt.comp_height,
        )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def _index_nodes(self) -> None:
        for n in self.doc.get("nodes", []) or []:
            self._nodes[str(n.get("id"))] = n
        known = set(self._nodes)
        for n in self._nodes.values():
            parent = n.get("parentId")
            key = parent if (parent in known) else None
            self._children.setdefault(key, []).append(n)
        for bucket in self._children.values():
            bucket.sort(key=lambda x: int(x.get("childIndex", 0)))

    def _visible_children(self, parent_id: Optional[str]) -> List[Dict[str, Any]]:
        out = []
        for n in self._children.get(parent_id, []):
            if not n.get("visible", True) and not self.opt.include_hidden:
                continue
            out.append(n)
        return out

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def build(self) -> BuildResult:
        roots = self._visible_children(None)
        if not roots:
            self.diag.error(
                "EMPTY_TRANSFER",
                "There was nothing to import. Select at least one visible layer and send again.",
            )
            return BuildResult(self.comp, self.manifest, self.diag)

        branches = [b for b in (self._build_node(n) for n in roots) if b is not None]
        output = self._composite(branches, "Root")

        if output:
            self.comp.active_tool = output
        self.manifest.diagnostics = self.diag.to_list()
        return BuildResult(self.comp, self.manifest, self.diag, output)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _build_node(self, node: Dict[str, Any]) -> Optional[_Branch]:
        kind = str(node.get("kind", ""))
        try:
            if node.get("fallback"):
                return self._build_fallback(node)
            if kind in CONTAINER_KINDS:
                return self._build_container(node)
            if kind == "TEXT":
                return self._build_text(node)
            if kind in SHAPE_KINDS:
                return self._build_shape(node)
            if kind == "RASTER":
                return self._build_fallback(node)
        except Exception as exc:  # pragma: no cover - defensive
            self.diag.error(
                "LAYER_FAILED",
                f'Layer "{node.get("name", "")}" could not be rebuilt and was skipped.',
                node_id=str(node.get("id")),
                node_name=str(node.get("name", "")),
                detail=f"{type(exc).__name__}: {exc}",
            )
            return None

        self.diag.warn(
            "UNSUPPORTED_LAYER_TYPE",
            f'Layer type "{kind}" is not supported and was skipped.',
            node_id=str(node.get("id")),
            node_name=str(node.get("name", "")),
        )
        return None

    # ------------------------------------------------------------------
    # Identity helper
    # ------------------------------------------------------------------

    def _identity(self, node: Dict[str, Any], role: str, part: str) -> Dict[str, Any]:
        return NodeIdentity(
            source=str((self.doc.get("source") or {}).get("app", "figma")),
            document_id=self.manifest.document_id,
            node_id=str(node.get("id")),
            transfer_id=self.manifest.transfer_id,
            schema_version=self.manifest.schema_version,
            role=role,
            part=part,
            node_name=str(node.get("name", "")),
        ).to_data()

    def _emit(
        self,
        node: Dict[str, Any],
        tool_id: str,
        part: str,
        inputs: Dict[str, Any],
        pos: Tuple[float, float],
        role: str = ROLE_SOURCE,
    ) -> Tool:
        name = self.names.allocate(str(node.get("name", "")), part)
        tool = Tool(tool_id, name, inputs, pos=pos, data=self._identity(node, role, part))
        self.comp.add(tool)
        self.manifest.record(str(node.get("id")), part, name)
        return tool

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _center_design_space(self, node: Dict[str, Any]) -> Tuple[float, float]:
        """The layer's visual centre in design coordinates.

        Design tools rotate a layer about its **top-left corner**, not its
        centre, and ``absoluteTransform`` encodes that: its translation is where
        the layer's local origin landed, not where its middle is. So the centre
        has to be found by pushing the local midpoint through the matrix.
        Adding half the width to the stored x is only correct for unrotated
        layers, and gets progressively more wrong as a layer is turned — which
        is exactly the kind of error that looks fine in a demo built from
        axis-aligned rectangles.
        """
        b = node.get("bounds") or {}
        w = float(b.get("width", 0.0))
        h = float(b.get("height", 0.0))
        m = node.get("absoluteTransform")
        if m:
            try:
                return mat_apply(m, w / 2.0, h / 2.0)
            except Exception:
                pass
        return (float(b.get("x", 0.0)) + w / 2.0, float(b.get("y", 0.0)) + h / 2.0)

    def _center_shape_space(self, node: Dict[str, Any]) -> Tuple[float, float]:
        cx, cy = self._center_design_space(node)
        return self.mapper.to_shape_space(cx, cy)

    def _center_image_space(self, node: Dict[str, Any]) -> Tuple[float, float]:
        cx, cy = self._center_design_space(node)
        return self.mapper.to_image_space(cx, cy)

    def _rotation(self, node: Dict[str, Any]) -> float:
        m = node.get("absoluteTransform")
        if m:
            try:
                return self.mapper.angle_to_fusion(decompose(m).rotation_deg)
            except Exception:
                pass
        return self.mapper.angle_to_fusion(float(node.get("rotation", 0.0)))

    def _corner_radius_normalised(self, node: Dict[str, Any]) -> float:
        """Design corner radius (px) -> Fusion shape ``CornerRadius`` (0..1).

        Fusion normalises against half the shorter side, so 1.0 is a pill. Four
        different radii cannot be expressed by one shape input; the largest is
        used and the difference is reported rather than quietly averaged.
        """
        geo = node.get("geometry") or {}
        radii = geo.get("cornerRadii")
        if not radii:
            return 0.0
        radii = [float(r) for r in radii]
        b = node.get("bounds") or {}
        short = min(float(b.get("width", 0.0)), float(b.get("height", 0.0)))
        if short <= 0:
            return 0.0

        if max(radii) - min(radii) > 0.01:
            self.diag.warn(
                "MIXED_CORNER_RADIUS",
                "This layer has different radii on each corner. Fusion shapes use "
                "one radius for all four, so the largest was used.",
                node_id=str(node.get("id")),
                node_name=str(node.get("name", "")),
            )
        if float(geo.get("cornerSmoothing", 0.0)) > 0.001:
            self.diag.warn(
                "CORNER_SMOOTHING_UNSUPPORTED",
                "Corner smoothing (squircle corners) has no Fusion equivalent; "
                "plain rounded corners were used.",
                node_id=str(node.get("id")),
                node_name=str(node.get("name", "")),
            )
        return max(0.0, min(1.0, max(radii) / (short / 2.0)))

    # ------------------------------------------------------------------
    # Paints
    # ------------------------------------------------------------------

    def _first_visible_paint(self, paints: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for p in paints or []:
            if p.get("visible", True):
                return p
        return None

    def _solid_rgba(self, paint: Dict[str, Any]) -> Tuple[float, float, float, float]:
        c = paint.get("color") or {}
        rgba = (float(c.get("r", 0.0)), float(c.get("g", 0.0)), float(c.get("b", 0.0)), float(c.get("a", 1.0)))
        rgba = convert_rgba(rgba, self.opt.color_policy)
        # Paint opacity folds into the paint's alpha. Layer opacity does not —
        # it stays on the Merge, so the two remain independently editable.
        return multiply_alpha(rgba, float(paint.get("opacity", 1.0)))

    def _gradient_background(
        self, node: Dict[str, Any], paint: Dict[str, Any], part: str, rib: int
    ) -> Optional[Tool]:
        """A native, fully editable Fusion gradient. Never a rendered bitmap."""
        b = node.get("bounds") or {}
        nx, ny = float(b.get("x", 0.0)), float(b.get("y", 0.0))
        nw, nh = float(b.get("width", 0.0)), float(b.get("height", 0.0))

        handles = paint.get("handles")
        try:
            if handles and handles.get("start") and handles.get("end"):
                geom = geometry_from_handles(
                    (handles["start"]["x"], handles["start"]["y"]),
                    (handles["end"]["x"], handles["end"]["y"]),
                    (handles.get("width") or {}).get("x") is not None
                    and (handles["width"]["x"], handles["width"]["y"])
                    or None,
                )
            else:
                geom = geometry_from_transform(paint.get("transform"))
        except Exception:
            self.diag.warn(
                "GRADIENT_DEGENERATE",
                "A gradient on this layer has no usable direction; a horizontal "
                "gradient was used instead.",
                node_id=str(node.get("id")),
                node_name=str(node.get("name", "")),
            )
            geom = geometry_from_handles((0.0, 0.5), (1.0, 0.5))

        # Handles are in normalised object space; move them into design pixels,
        # then into Fusion image space.
        start = self.mapper.to_image_space(nx + geom.start[0] * nw, ny + geom.start[1] * nh)
        end = self.mapper.to_image_space(nx + geom.end[0] * nw, ny + geom.end[1] * nh)

        gtype = map_gradient_type(str(paint.get("type", "")))
        if not gtype.exact:
            self.diag.warn(
                "GRADIENT_APPROXIMATED",
                gtype.note,
                node_id=str(node.get("id")),
                node_name=str(node.get("name", "")),
            )

        stops = build_stops(
            paint.get("stops") or [],
            float(paint.get("opacity", 1.0)),
            self.opt.color_policy,
        )

        return self._emit(
            node,
            "Background",
            part,
            {
                "Width": self.opt.comp_width,
                "Height": self.opt.comp_height,
                "UseFrameFormatSettings": 1,
                "Type": FuID("Gradient"),
                "GradientType": FuID(gtype.fu_id),
                "Start": Vec(start[0], start[1]),
                "End": Vec(end[0], end[1]),
                "Gradient": Gradient(stops),
            },
            self.layout.rib_step(rib),
        )

    # ------------------------------------------------------------------
    # Shapes
    # ------------------------------------------------------------------

    def _shape_tool_for(self, node: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Pick the native Fusion shape tool and its shape-specific inputs."""
        kind = str(node.get("kind"))
        b = node.get("bounds") or {}
        w = self.mapper.length_to_shape_space(float(b.get("width", 0.0)))
        h = self.mapper.length_to_shape_space(float(b.get("height", 0.0)))
        geo = node.get("geometry") or {}

        if kind == "RECTANGLE":
            return "sRectangle", {
                "Width": w,
                "Height": h,
                "CornerRadius": self._corner_radius_normalised(node),
            }
        if kind == "ELLIPSE":
            if geo.get("arc"):
                self.diag.warn(
                    "ARC_UNSUPPORTED",
                    "Arc and donut ellipses are drawn as full ellipses; Fusion's "
                    "ellipse shape has no sweep control.",
                    node_id=str(node.get("id")),
                    node_name=str(node.get("name", "")),
                )
            return "sEllipse", {"Width": w, "Height": h}
        if kind == "POLYGON":
            return "sNGon", {
                "Width": w,
                "Height": h,
                "Sides": int(geo.get("pointCount") or 3),
            }
        if kind == "STAR":
            return "sStar", {
                "Width": w,
                "Height": h,
                "Sides": int(geo.get("pointCount") or 5),
            }
        if kind == "LINE":
            # A line is a zero-height rectangle; the stroke gives it thickness,
            # which keeps start/end, weight and caps editable.
            stroke = node.get("stroke") or {}
            weight = self.mapper.length_to_shape_space(float(stroke.get("weight", 1.0)))
            return "sRectangle", {"Width": w if w > 0 else h, "Height": max(weight, 1e-5), "CornerRadius": 0}
        return None

    def _build_shape(self, node: Dict[str, Any]) -> Optional[_Branch]:
        strategy = self.opt.vector_strategy
        kind = str(node.get("kind"))

        if strategy == "RASTER" or kind in ("VECTOR", "BOOLEAN_OPERATION"):
            if node.get("fallback"):
                return self._build_fallback(node)
            if kind in ("VECTOR", "BOOLEAN_OPERATION"):
                self.diag.warn(
                    "VECTOR_NOT_EXPORTED",
                    "This vector layer needs an exported outline, but none was "
                    "included in the transfer. It was skipped.",
                    node_id=str(node.get("id")),
                    node_name=str(node.get("name", "")),
                )
                return None

        picked = self._shape_tool_for(node)
        if picked is None:
            return self._build_fallback(node) if node.get("fallback") else None

        tool_id, shape_inputs = picked
        rib = self.layout.new_rib()
        cx, cy = self._center_shape_space(node)
        angle = self._rotation(node)

        fill_paint = self._first_visible_paint(node.get("fills") or [])
        stroke = node.get("stroke") or {}
        stroke_paint = self._first_visible_paint(stroke.get("paints") or [])
        stroke_weight = float(stroke.get("weight", 0.0))
        has_stroke = stroke_paint is not None and stroke_weight > 0

        shape_outputs: List[str] = []
        gradient_fill_tool: Optional[str] = None

        # ---- fill branch -------------------------------------------------
        if fill_paint is not None:
            if fill_paint.get("type") == "IMAGE":
                img = self._build_image_paint(node, fill_paint, rib)
                if img:
                    shape_outputs.append(img)
            else:
                inputs = dict(shape_inputs)
                inputs.update({
                    "Solid": 1,
                    "Angle": angle,
                    "Translate.X": cx,
                    "Translate.Y": cy,
                })
                is_grad = str(fill_paint.get("type", "")).startswith("GRADIENT_")
                if is_grad:
                    # A gradient fill is a gradient Background masked by the
                    # shape, which keeps both the gradient stops and the shape
                    # geometry editable — neither is baked into the other.
                    inputs["Red"], inputs["Green"], inputs["Blue"] = 1.0, 1.0, 1.0
                else:
                    r, g, b, a = self._solid_rgba(fill_paint)
                    inputs.update({"Red": r, "Green": g, "Blue": b, "Alpha": a})

                shape = self._emit(node, tool_id, "Shape", inputs, self.layout.rib_step(rib))
                rendered = self._emit(
                    node, "sRender", "Fill",
                    {
                        "Input": Link(shape.name),
                        "Width": self.opt.comp_width,
                        "Height": self.opt.comp_height,
                        "UseFrameFormatSettings": 1,
                    },
                    self.layout.rib_step(rib),
                )
                if is_grad:
                    grad = self._gradient_background(node, fill_paint, "FillGradient", rib)
                    if grad:
                        masked = self._emit(
                            node, "Merge", "FillMasked",
                            {
                                "Background": Link(grad.name),
                                "Foreground": Link(rendered.name),
                                "ApplyMode": FuID("Multiply"),
                                "AlphaMode": 0,
                            },
                            self.layout.rib_step(rib),
                        )
                        gradient_fill_tool = masked.name
                        shape_outputs.append(masked.name)
                    else:
                        shape_outputs.append(rendered.name)
                else:
                    shape_outputs.append(rendered.name)

        # ---- stroke branch ----------------------------------------------
        if has_stroke:
            stroke_name = self._build_stroke(node, tool_id, stroke, stroke_paint, rib, angle)
            if stroke_name:
                shape_outputs.append(stroke_name)

        if not shape_outputs:
            self.diag.info(
                "LAYER_INVISIBLE",
                f'Layer "{node.get("name", "")}" has no fill or stroke, so nothing was created for it.',
                node_id=str(node.get("id")),
                node_name=str(node.get("name", "")),
            )
            return None

        current = shape_outputs[0]
        for extra in shape_outputs[1:]:
            merged = self._emit(
                node, "Merge", "FillStroke",
                {"Background": Link(current), "Foreground": Link(extra)},
                self.layout.rib_step(rib),
            )
            current = merged.name

        current = self._apply_effects(node, current, rib)
        current = self._add_animation_slot(node, current, rib)
        self.layout.align_rib_to_spine(rib)

        return _Branch(
            tool_name=current,
            node_id=str(node.get("id")),
            opacity=float(node.get("opacity", 1.0)),
            blend_mode=str(node.get("blendMode", "NORMAL")),
            is_mask=bool(node.get("isMask", False)),
        )

    def _build_stroke(
        self,
        node: Dict[str, Any],
        tool_id: str,
        stroke: Dict[str, Any],
        paint: Dict[str, Any],
        rib: int,
        angle: float,
    ) -> Optional[str]:
        """Build the stroke as its own branch, aligned the way the design asks."""
        from .stroke import dash_warning, ellipse_stroke_geometry, polygon_stroke_geometry, rect_stroke_geometry

        b = node.get("bounds") or {}
        w_px, h_px = float(b.get("width", 0.0)), float(b.get("height", 0.0))
        weight = float(stroke.get("weight", 0.0))
        align = str(stroke.get("align", "CENTER"))
        kind = str(node.get("kind"))
        geo_spec = node.get("geometry") or {}

        if kind == "ELLIPSE":
            geom = ellipse_stroke_geometry(w_px, h_px, weight, align)
        elif kind in ("POLYGON", "STAR"):
            geom = polygon_stroke_geometry(w_px, h_px, weight, align, int(geo_spec.get("pointCount") or 3))
        else:
            radii = geo_spec.get("cornerRadii") or (0.0, 0.0, 0.0, 0.0)
            geom = rect_stroke_geometry(w_px, h_px, weight, align, radii)

        if geom.warning:
            self.diag.warn(
                "STROKE_GEOMETRY", geom.warning,
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )
        dw = dash_warning(stroke.get("dashPattern") or [])
        if dw:
            self.diag.warn(
                "STROKE_DASHED", dw,
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )

        cx, cy = self._center_shape_space(node)
        inputs: Dict[str, Any] = {
            "Width": self.mapper.length_to_shape_space(geom.width),
            "Height": self.mapper.length_to_shape_space(geom.height),
            "Solid": 0,
            "BorderWidth": self.mapper.length_to_shape_space(geom.thickness),
            "Angle": angle,
            "Translate.X": cx,
            "Translate.Y": cy,
        }
        if tool_id == "sRectangle":
            short = min(geom.width, geom.height)
            inputs["CornerRadius"] = (
                max(0.0, min(1.0, max(geom.corner_radii) / (short / 2.0))) if short > 0 else 0.0
            )
        if tool_id in ("sNGon", "sStar"):
            inputs["Sides"] = int(geo_spec.get("pointCount") or 3)

        is_grad = str(paint.get("type", "")).startswith("GRADIENT_")
        if is_grad:
            inputs.update({"Red": 1.0, "Green": 1.0, "Blue": 1.0, "Alpha": 1.0})
        elif paint.get("type") == "IMAGE":
            self.diag.warn(
                "STROKE_IMAGE_UNSUPPORTED",
                "Image strokes are not supported; the stroke was drawn in a flat colour.",
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )
            inputs.update({"Red": 0.5, "Green": 0.5, "Blue": 0.5, "Alpha": 1.0})
        else:
            r, g, bch, a = self._solid_rgba(paint)
            inputs.update({"Red": r, "Green": g, "Blue": bch, "Alpha": a})

        shape = self._emit(node, tool_id, "Stroke", inputs, self.layout.rib_step(rib))
        rendered = self._emit(
            node, "sRender", "StrokeRender",
            {
                "Input": Link(shape.name),
                "Width": self.opt.comp_width,
                "Height": self.opt.comp_height,
                "UseFrameFormatSettings": 1,
            },
            self.layout.rib_step(rib),
        )

        if is_grad:
            grad = self._gradient_background(node, paint, "StrokeGradient", rib)
            if grad:
                masked = self._emit(
                    node, "Merge", "StrokeMasked",
                    {
                        "Background": Link(grad.name),
                        "Foreground": Link(rendered.name),
                        "ApplyMode": FuID("Multiply"),
                        "AlphaMode": 0,
                    },
                    self.layout.rib_step(rib),
                )
                return masked.name
        return rendered.name

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def _build_text(self, node: Dict[str, Any]) -> Optional[_Branch]:
        text = node.get("text") or {}
        if not text:
            return None

        rib = self.layout.new_rib()
        b = node.get("bounds") or {}
        font = text.get("font") or {}
        family = str(font.get("family", ""))
        style = str(font.get("style", "Regular"))

        match = self.fonts.resolve(family, style, str(font.get("postScriptName", "")))
        if match.confidence == MISSING:
            self.diag.warn(
                "FONT_MISSING", match.note,
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
                detail=f"{family} / {style}",
            )
        elif match.confidence != EXACT:
            self.diag.warn(
                "FONT_STYLE_SUBSTITUTED", match.note,
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )

        # Text+ Size is a fraction of the composition height.
        font_size_px = float(text.get("fontSize", 16.0)) * self.mapper.scale
        size = font_size_px / float(self.opt.comp_height)

        fill = self._first_visible_paint(text.get("fills") or node.get("fills") or [])
        if fill is not None and fill.get("type") == "SOLID":
            r, g, bch, a = self._solid_rgba(fill)
        else:
            r, g, bch, a = 1.0, 1.0, 1.0, 1.0
            if fill is not None:
                self.diag.warn(
                    "TEXT_FILL_APPROXIMATED",
                    "Gradient and image fills on text are not reproduced; the text "
                    "was created in white so it can be re-coloured in Fusion.",
                    node_id=str(node.get("id")), node_name=str(node.get("name", "")),
                )

        h_align = {"LEFT": 0, "CENTER": 1, "RIGHT": 2, "JUSTIFIED": 3}.get(
            str(text.get("alignHorizontal", "LEFT")), 0
        )
        v_align = {"TOP": 0, "CENTER": 1, "BOTTOM": 2}.get(str(text.get("alignVertical", "TOP")), 0)
        if str(text.get("alignHorizontal")) == "JUSTIFIED":
            self.diag.info(
                "TEXT_JUSTIFIED",
                "Justified text was created using Fusion's justify mode; line "
                "breaks may fall differently from the design.",
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )

        inputs: Dict[str, Any] = {
            "Width": self.opt.comp_width,
            "Height": self.opt.comp_height,
            "UseFrameFormatSettings": 1,
            "StyledText": str(text.get("characters", "")),
            "Font": match.family,
            "Style": match.style,
            "Size": size,
            "HorizontalJustificationNew": h_align,
            "VerticalJustificationNew": v_align,
            "Red1": r, "Green1": g, "Blue1": bch, "Alpha1": a,
        }

        ls = text.get("letterSpacing") or {}
        if ls.get("unit") == "PERCENT":
            inputs["CharacterSpacing"] = 1.0 + float(ls.get("value", 0.0)) / 100.0
        elif ls.get("unit") == "PIXELS" and font_size_px > 0:
            inputs["CharacterSpacing"] = 1.0 + float(ls.get("value", 0.0)) / font_size_px

        lh = text.get("lineHeight") or {}
        if lh.get("unit") == "PERCENT":
            inputs["LineSpacing"] = float(lh.get("value", 100.0)) / 100.0
        elif lh.get("unit") == "PIXELS" and font_size_px > 0:
            inputs["LineSpacing"] = float(lh.get("value", 0.0)) / font_size_px

        if text.get("hasMixedStyles"):
            self.diag.warn(
                "TEXT_MIXED_STYLES",
                "This text mixes fonts or sizes. It was created as one editable "
                "Text+ using the dominant style; re-style the runs in Fusion if needed.",
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )

        tool = self._emit(node, "TextPlus", "Text", inputs, self.layout.rib_step(rib))

        # Text+ renders centred in the comp, so position it with a Transform.
        ix, iy = self._center_image_space(node)
        placed = self._emit(
            node, "Transform", "TextPlace",
            {"Input": Link(tool.name), "Center": Point(ix, iy), "Angle": self._rotation(node)},
            self.layout.rib_step(rib),
        )

        current = self._apply_effects(node, placed.name, rib)
        current = self._add_animation_slot(node, current, rib)
        self.layout.align_rib_to_spine(rib)

        return _Branch(
            tool_name=current,
            node_id=str(node.get("id")),
            opacity=float(node.get("opacity", 1.0)),
            blend_mode=str(node.get("blendMode", "NORMAL")),
            is_mask=bool(node.get("isMask", False)),
        )

    # ------------------------------------------------------------------
    # Images and raster fallbacks
    # ------------------------------------------------------------------

    def _build_image_paint(self, node: Dict[str, Any], paint: Dict[str, Any], rib: int) -> Optional[str]:
        asset_id = str(paint.get("assetId", ""))
        path = self.opt.asset_paths.get(asset_id)
        if not path:
            self.diag.error(
                "ASSET_MISSING",
                f'The image used by "{node.get("name", "")}" is not in the asset cache.',
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
                detail=f"assetId={asset_id}",
            )
            return None

        loader = self._emit(
            node, "Loader", "Image",
            {"Clip": path, "Loop": 1, "GlobalIn": 0},
            self.layout.rib_step(rib),
        )

        b = node.get("bounds") or {}
        ix, iy = self._center_image_space(node)

        scale_mode = str(paint.get("scaleMode", "FILL"))
        if scale_mode == "TILE" and path.lower().endswith(".png"):
            import struct
            with open(path, "rb") as image_file:
                header = image_file.read(24)
            if header[:8] != b"\x89PNG\r\n\x1a\n" or len(header) != 24:
                raise ValueError("Invalid PNG tile")
            tile_w, tile_h = struct.unpack(">II", header[16:24])
            factor = float(paint.get("scalingFactor", 1.0))
            if not tile_w or not tile_h or factor <= 0:
                raise ValueError("Invalid tile dimensions or scale")
            # Wrap a source image at its pixel size; do not shrink it relative
            # to the composition width. Anchor the first tile to the layer.
            px, py = float(b.get("x", 0)), float(b.get("y", 0))
            tx, ty = self.mapper.to_image_space(px + tile_w * factor / 2,
                                               py + tile_h * factor / 2)
            canvas = self._emit(node, "Background", "ImageCanvas", {
                "Width": self.opt.comp_width, "Height": self.opt.comp_height,
                "UseFrameFormatSettings": 1, "TopLeftAlpha": 0,
            }, self.layout.rib_step(rib))
            placed = self._emit(node, "Merge", "ImagePlace", {
                "Background": Link(canvas.name), "Foreground": Link(loader.name),
                "Center": Point(tx, ty), "Size": factor * self.mapper.scale,
                "Edges": 1, "PerformDepthMerge": 0,
            }, self.layout.rib_step(rib))
            if self._rotation(node) or float(paint.get("rotation", 0)):
                self.diag.warn("TILE_ROTATION_UNSUPPORTED", "Rotated image tiles need manual alignment.",
                               node_id=str(node.get("id")))
            return placed.name
        if scale_mode in ("TILE", "CROP"):
            self.diag.warn(
                "IMAGE_SCALE_MODE_APPROXIMATED",
                f'Image scale mode "{scale_mode}" was approximated; check the '
                "framing of this image in Fusion.",
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
            )

        sw, _sh = self.mapper.size_to_image_space(float(b.get("width", 0.0)), float(b.get("height", 0.0)))
        placed = self._emit(
            node, "Transform", "ImagePlace",
            {
                "Input": Link(loader.name),
                "Center": Point(ix, iy),
                "Angle": self._rotation(node) - float(paint.get("rotation", 0.0)),
                "Size": max(sw, 1e-6),
            },
            self.layout.rib_step(rib),
        )
        return placed.name

    def _build_fallback(self, node: Dict[str, Any]) -> Optional[_Branch]:
        fb = node.get("fallback") or {}
        asset_id = str(fb.get("assetId", ""))
        path = self.opt.asset_paths.get(asset_id)
        if not path:
            self.diag.error(
                "ASSET_MISSING",
                f'"{node.get("name", "")}" was exported as an image, but the file is missing.',
                node_id=str(node.get("id")), node_name=str(node.get("name", "")),
                detail=f"assetId={asset_id}",
            )
            return None

        self.diag.info(
            "LAYER_RASTERISED",
            f'"{node.get("name", "")}" could not be rebuilt with Fusion shapes '
            f'({fb.get("reason", "unsupported geometry")}), so it was imported as an image.',
            node_id=str(node.get("id")), node_name=str(node.get("name", "")),
        )

        rib = self.layout.new_rib()
        loader = self._emit(
            node, "Loader", "Raster",
            {"Clip": path, "Loop": 1, "GlobalIn": 0},
            self.layout.rib_step(rib),
        )

        b = node.get("bounds") or {}
        ix, iy = self._center_image_space(node)
        export_scale = max(float(fb.get("exportScale", 1.0)), 1e-6)

        placed = self._emit(
            node, "Transform", "RasterPlace",
            {
                "Input": Link(loader.name),
                "Center": Point(ix, iy),
                "Angle": self._rotation(node),
                # Exported at N times size for crispness; scale back down so it
                # lands at design size but keeps its extra resolution.
                "Size": self.mapper.scale / export_scale,
            },
            self.layout.rib_step(rib),
        )

        current = self._apply_effects(node, placed.name, rib)
        current = self._add_animation_slot(node, current, rib)
        self.layout.align_rib_to_spine(rib)

        return _Branch(
            tool_name=current,
            node_id=str(node.get("id")),
            opacity=float(node.get("opacity", 1.0)),
            blend_mode=str(node.get("blendMode", "NORMAL")),
            is_mask=bool(node.get("isMask", False)),
        )

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    def _build_container(self, node: Dict[str, Any]) -> Optional[_Branch]:
        node_id = str(node.get("id"))
        children = self._visible_children(node_id)

        child_branches = [b for b in (self._build_node(c) for c in children) if b is not None]

        # A frame can paint its own background before its children.
        own_fill = self._first_visible_paint(node.get("fills") or [])
        if own_fill is not None and str(node.get("kind")) in ("FRAME", "COMPONENT", "INSTANCE", "SECTION"):
            bg = self._build_frame_background(node)
            if bg:
                child_branches.insert(0, bg)

        if not child_branches:
            return None

        composed = self._composite(child_branches, str(node.get("name", "Group")))
        if composed is None:
            return None

        rib = self.layout.new_rib()
        composed = self._apply_clip(node, composed, rib)
        composed = self._apply_effects(node, composed, rib)
        composed = self._add_animation_slot(node, composed, rib)
        self.layout.align_rib_to_spine(rib)

        self.manifest.record(node_id, "Container", composed)
        return _Branch(
            tool_name=composed,
            node_id=node_id,
            opacity=float(node.get("opacity", 1.0)),
            blend_mode=str(node.get("blendMode", "NORMAL")),
            is_mask=bool(node.get("isMask", False)),
        )

    def _build_frame_background(self, node: Dict[str, Any]) -> Optional[_Branch]:
        """A frame's own fill, drawn as a rectangle behind its children."""
        synthetic = dict(node)
        synthetic["kind"] = "RECTANGLE"
        synthetic["stroke"] = node.get("stroke")
        synthetic["effects"] = []
        synthetic["opacity"] = 1.0
        branch = self._build_shape(synthetic)
        return branch

    def _apply_clip(self, node: Dict[str, Any], input_tool: str, rib: int) -> str:
        """Clip a frame's contents to its bounds."""
        mode = self.opt.clip_frames
        should_clip = (
            mode == "ON"
            or (mode == "AUTO" and bool(node.get("clipsContent", False)))
        )
        if not should_clip:
            return input_tool

        b = node.get("bounds") or {}
        ix, iy = self._center_image_space(node)
        mw, mh = self.mapper.size_to_image_space(float(b.get("width", 0.0)), float(b.get("height", 0.0)))

        geo = node.get("geometry") or {}
        radii = geo.get("cornerRadii") or (0, 0, 0, 0)
        short = min(float(b.get("width", 0.0)), float(b.get("height", 0.0)))
        corner = max(0.0, min(1.0, max(float(r) for r in radii) / (short / 2.0))) if short > 0 else 0.0

        mask = self._emit(
            node, "RectangleMask", "ClipMask",
            {
                "MaskWidth": self.opt.comp_width,
                "MaskHeight": self.opt.comp_height,
                "UseFrameFormatSettings": 1,
                "Center": Point(ix, iy),
                "Width": mw,
                "Height": mh,
                "CornerRadius": corner,
                "Angle": self._rotation(node),
                "Solid": 1,
            },
            self.layout.rib_step(rib),
        )
        clipped = self._emit(
            node, "Background", "ClipCanvas",
            {"Width": self.opt.comp_width, "Height": self.opt.comp_height,
             "UseFrameFormatSettings": 1, "TopLeftAlpha": 0},
            self.layout.rib_step(rib),
        )
        clipped = self._emit(
            node, "Merge", "Clip",
            {"Background": Link(clipped.name), "Foreground": Link(input_tool),
             "EffectMask": Link(mask.name, "Mask")},
            self.layout.rib_step(rib),
        )
        return clipped.name

    # ------------------------------------------------------------------
    # Effects and compositing
    # ------------------------------------------------------------------

    def _apply_effects(self, node: Dict[str, Any], input_tool: str, rib: int) -> str:
        """Apply effects in the order the design tool paints them."""
        current = input_tool
        for eff in node.get("effects") or []:
            if not eff.get("visible", True):
                continue
            etype = str(eff.get("type"))

            if etype == "LAYER_BLUR":
                size = blur_radius_to_fusion_size(
                    float(eff.get("radius", 0.0)) * self.mapper.scale, self.opt.comp_width
                )
                tool = self._emit(
                    node, "Blur", "Blur",
                    {"Input": Link(current), "XBlurSize": size, "LockXY": 1},
                    self.layout.rib_step(rib),
                )
                current = tool.name

            elif etype == "DROP_SHADOW":
                c = eff.get("color") or {}
                params = drop_shadow_params(
                    [float((eff.get("offset") or {}).get("x", 0.0)), float((eff.get("offset") or {}).get("y", 0.0))],
                    float(eff.get("radius", 0.0)),
                    float(eff.get("spread", 0.0)),
                    convert_rgba(
                        (float(c.get("r", 0)), float(c.get("g", 0)), float(c.get("b", 0)), float(c.get("a", 1))),
                        self.opt.color_policy,
                    ),
                    self.opt.comp_width, self.opt.comp_height, self.mapper.scale,
                )
                if params.warning:
                    self.diag.warn(
                        "SHADOW_SPREAD", params.warning,
                        node_id=str(node.get("id")), node_name=str(node.get("name", "")),
                    )
                tool = self._emit(
                    node, "Shadow", "Shadow",
                    {
                        "Input": Link(current),
                        "ShadowOffset": Point(params.offset_x, params.offset_y),
                        "Softness": params.softness,
                        "Red": params.color[0], "Green": params.color[1],
                        "Blue": params.color[2], "Alpha": params.color[3],
                    },
                    self.layout.rib_step(rib),
                )
                current = tool.name

            elif etype == "INNER_SHADOW":
                current = self._build_inner_shadow(node, current, eff, rib)

            elif etype == "BACKGROUND_BLUR":
                self.diag.warn(
                    "BACKGROUND_BLUR_EXPERIMENTAL", background_blur_support_note(),
                    node_id=str(node.get("id")), node_name=str(node.get("name", "")),
                )
        return current

    def _build_inner_shadow(
        self, node: Dict[str, Any], input_tool: str, eff: Dict[str, Any], rib: int
    ) -> str:
        """Build an inner shadow from real, editable Fusion nodes.

        Fusion has no inner-shadow tool, but the effect decomposes exactly:
        invert the layer's matte so the outside becomes solid, offset and blur
        it, clip it back to the layer's own alpha, tint it, and merge it on top.
        Every step stays adjustable in the Inspector.
        """
        c = eff.get("color") or {}
        plan = inner_shadow_plan(
            [float((eff.get("offset") or {}).get("x", 0.0)), float((eff.get("offset") or {}).get("y", 0.0))],
            float(eff.get("radius", 0.0)),
            float(eff.get("spread", 0.0)),
            convert_rgba(
                (float(c.get("r", 0)), float(c.get("g", 0)), float(c.get("b", 0)), float(c.get("a", 1))),
                self.opt.color_policy,
            ),
            self.opt.comp_width, self.opt.comp_height, self.mapper.scale,
        )

        inverted = self._emit(
            node, "ChannelBoolean", "InnerInvert",
            {"Background": Link(input_tool), "Operation": FuID("Negative"),
             "ToRed": 4, "ToGreen": 4, "ToBlue": 4, "ToAlpha": 3},
            self.layout.rib_step(rib),
        )
        moved = self._emit(
            node, "Transform", "InnerOffset",
            {"Input": Link(inverted.name), "Center": Point(0.5 + plan.offset_x, 0.5 + plan.offset_y)},
            self.layout.rib_step(rib),
        )
        blurred = self._emit(
            node, "Blur", "InnerBlur",
            {"Input": Link(moved.name), "XBlurSize": plan.softness, "LockXY": 1},
            self.layout.rib_step(rib),
        )
        tinted = self._emit(
            node, "Background", "InnerColor",
            {
                "Width": self.opt.comp_width, "Height": self.opt.comp_height,
                "UseFrameFormatSettings": 1,
                "TopLeftRed": plan.color[0], "TopLeftGreen": plan.color[1],
                "TopLeftBlue": plan.color[2], "TopLeftAlpha": plan.color[3],
                "EffectMask": Link(blurred.name),
            },
            self.layout.rib_step(rib),
        )
        merged = self._emit(
            node, "Merge", "InnerShadow",
            {
                "Background": Link(input_tool),
                "Foreground": Link(tinted.name),
                # Clip the shadow to the layer it belongs to.
                "EffectMask": Link(input_tool),
            },
            self.layout.rib_step(rib),
        )
        self.diag.info(
            "INNER_SHADOW_BUILT", plan.note,
            node_id=str(node.get("id")), node_name=str(node.get("name", "")),
        )
        return merged.name

    def _add_animation_slot(self, node: Dict[str, Any], input_tool: str, rib: int) -> str:
        """The Transform that belongs to the user, not to the design.

        Re-sync rebuilds everything upstream of this node and never writes to
        this node itself, so keyframes placed here survive any number of design
        updates. This one node is the entire animation-preservation contract.
        """
        name = self.names.allocate(str(node.get("name", "")), "Anim")
        tool = Tool(
            "Transform", name,
            {"Input": Link(input_tool)},
            pos=self.layout.rib_step(rib),
            data=self._identity(node, ROLE_USER, "Anim"),
            comments="Animate here. Figma Fusion Bridge never overwrites this node.",
        )
        self.comp.add(tool)
        self.manifest.record(str(node.get("id")), "Anim", name)
        return name

    def _composite(self, branches: List[_Branch], label: str) -> Optional[str]:
        """Merge branches bottom-up, preserving z-order and masks."""
        if not branches:
            return None

        pending_mask: Optional[str] = None
        current: Optional[str] = None

        for branch in branches:
            if branch.is_mask:
                # A mask layer applies to the layers above it, so hold it until
                # the next branch arrives rather than compositing it directly.
                pending_mask = branch.tool_name
                continue

            if current is None:
                current = branch.tool_name
                if pending_mask:
                    current = self._mask_wrap(branch, current, pending_mask, label)
                    pending_mask = None
                if branch.opacity < 0.999:
                    current = self._opacity_wrap(branch, current, label)
                continue

            mapping = map_blend_mode(branch.blend_mode)
            if mapping.note:
                self.diag.warn(
                    "BLEND_MODE_APPROXIMATED", mapping.note,
                    node_id=branch.node_id,
                )

            inputs: Dict[str, Any] = {
                "Background": Link(current),
                "Foreground": Link(branch.tool_name),
            }
            if mapping.apply_mode:
                inputs["ApplyMode"] = FuID(mapping.apply_mode)
            # Layer opacity lives here, kept separate from any paint opacity.
            if branch.opacity < 0.999:
                inputs["Blend"] = branch.opacity
            if pending_mask:
                inputs["EffectMask"] = Link(pending_mask)
                pending_mask = None

            name = self.names.allocate(label, "Merge")
            tool = Tool("Merge", name, inputs, pos=self.layout.next_spine())
            self.comp.add(tool)
            current = name

        return current

    def _mask_wrap(self, branch: _Branch, current: str, mask_tool: str, label: str) -> str:
        name = self.names.allocate(label, "Masked")
        self.comp.add(
            Tool("Transform", name, {"Input": Link(current), "EffectMask": Link(mask_tool)},
                 pos=self.layout.next_spine())
        )
        return name

    def _opacity_wrap(self, branch: _Branch, current: str, label: str) -> str:
        """Apply opacity to a bottom-most layer, which has no Merge to carry it."""
        name = self.names.allocate(label, "Opacity")
        self.comp.add(
            Tool("Merge", name, {"Foreground": Link(current), "Blend": branch.opacity},
                 pos=self.layout.next_spine())
        )
        return name


def build_graph(
    document: Dict[str, Any],
    options: Optional[BuildOptions] = None,
    font_resolver: Optional[FontResolver] = None,
) -> BuildResult:
    """Convenience entry point."""
    return FusionGraphBuilder(document, options, font_resolver).build()
