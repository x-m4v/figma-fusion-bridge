"""Stroke geometry.

Fusion shape tools draw a stroke centred on the path: ``Solid = 0`` switches the
shape from filled to outlined and ``BorderWidth`` sets the thickness. There is
no inside/outside alignment control, so alignment has to be reproduced
geometrically.

The construction is exact for the shapes it is applied to, not a fudge factor:
an inside stroke of weight *t* on a box of size *W x H* covers precisely the
same pixels as a centred stroke of weight *t* on a box of size *(W-t) x (H-t)*,
because both describe the band between the original edge and an edge inset by
*t*. Outside strokes are the same construction with the sign flipped.

Corner radii shift with the edge for the same reason: the centre of curvature
does not move, so the radius of the offset path is the original radius plus the
offset, floored at zero where the corner has gone square.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

INSIDE = "INSIDE"
OUTSIDE = "OUTSIDE"
CENTER = "CENTER"


@dataclass(frozen=True)
class StrokeGeometry:
    """The centred-stroke shape that reproduces an aligned stroke."""

    #: Size of the path the centred stroke is drawn on, in design pixels.
    width: float
    height: float
    #: Centred stroke thickness, in design pixels. Equals the design weight.
    thickness: float
    #: Corner radii for that path, in design pixels (TL, TR, BR, BL).
    corner_radii: Tuple[float, float, float, float]
    #: How far the path centre moved from the node's own centre. Always zero for
    #: symmetric shapes, kept explicit so asymmetric cases stay expressible.
    offset: Tuple[float, float] = (0.0, 0.0)
    #: Set when the requested geometry could not be produced faithfully.
    warning: str = ""


def _offset_for(align: str, weight: float) -> float:
    """Signed edge offset. Positive grows the path, negative shrinks it."""
    if align == INSIDE:
        return -weight / 2.0
    if align == OUTSIDE:
        return weight / 2.0
    return 0.0


def rect_stroke_geometry(
    width: float,
    height: float,
    weight: float,
    align: str,
    corner_radii: Sequence[float] = (0.0, 0.0, 0.0, 0.0),
) -> StrokeGeometry:
    """Stroke path for a rectangle, honouring alignment.

    An inside stroke thicker than half the box would collapse the path to
    negative size. Rather than emitting a degenerate shape, the path is clamped
    to zero and a warning is raised — in the design tool that case renders as a
    fully filled box, and the caller can act on the warning to do the same.
    """
    off = _offset_for(align, weight)
    w = width + 2.0 * off
    h = height + 2.0 * off
    warning = ""

    if w <= 0.0 or h <= 0.0:
        warning = (
            "The inside stroke is thicker than the shape, so it fills it "
            "completely. A filled shape is used instead of an outline."
        )
        w = max(w, 0.0)
        h = max(h, 0.0)

    radii = tuple(max(0.0, float(r) + off) for r in tuple(corner_radii)[:4]) or (0.0, 0.0, 0.0, 0.0)
    while len(radii) < 4:
        radii = radii + (0.0,)

    return StrokeGeometry(
        width=w,
        height=h,
        thickness=abs(weight),
        corner_radii=(radii[0], radii[1], radii[2], radii[3]),
        warning=warning,
    )


def ellipse_stroke_geometry(width: float, height: float, weight: float, align: str) -> StrokeGeometry:
    """Stroke path for an ellipse.

    Offsetting an ellipse is not exactly an ellipse — the true offset curve is a
    higher-order rational — but for the stroke weights used in interface design
    (a few pixels against radii of tens or hundreds) the elliptical
    approximation is below a tenth of a pixel. It is flagged only when the
    weight is large enough relative to the radius for the error to become
    visible.
    """
    off = _offset_for(align, weight)
    w = max(0.0, width + 2.0 * off)
    h = max(0.0, height + 2.0 * off)

    warning = ""
    min_radius = min(width, height) / 2.0
    if min_radius > 0 and abs(off) / min_radius > 0.25:
        warning = (
            "This stroke is very thick relative to the ellipse, so its inner or "
            "outer edge is approximated and may differ slightly from the design."
        )
    if width + 2.0 * off <= 0.0 or height + 2.0 * off <= 0.0:
        warning = (
            "The inside stroke is thicker than the ellipse, so it fills it "
            "completely. A filled shape is used instead of an outline."
        )

    return StrokeGeometry(
        width=w, height=h, thickness=abs(weight), corner_radii=(0.0, 0.0, 0.0, 0.0), warning=warning
    )


def polygon_stroke_geometry(
    width: float, height: float, weight: float, align: str, sides: int
) -> StrokeGeometry:
    """Stroke path for a regular polygon.

    A polygon's offset path is a similar polygon, but the *apothem* moves by the
    offset, not the circumradius. Scaling the circumradius by the offset
    directly would place the edges wrong by a factor of ``1/cos(pi/n)`` — about
    15% for a triangle. The correction is applied here rather than reusing the
    rectangle path.
    """
    import math

    off = _offset_for(align, weight)
    n = max(3, int(sides))
    # Circumradius offset that moves each edge by exactly `off`.
    r_off = off / math.cos(math.pi / n)
    w = max(0.0, width + 2.0 * r_off)
    h = max(0.0, height + 2.0 * r_off)

    warning = ""
    if width + 2.0 * r_off <= 0.0 or height + 2.0 * r_off <= 0.0:
        warning = (
            "The inside stroke is thicker than the polygon, so it fills it "
            "completely. A filled shape is used instead of an outline."
        )

    return StrokeGeometry(
        width=w, height=h, thickness=abs(weight), corner_radii=(0.0, 0.0, 0.0, 0.0), warning=warning
    )


def dash_warning(dash_pattern: Sequence[float]) -> Optional[str]:
    """Fusion shape strokes are continuous; dashes need a different construction."""
    if dash_pattern:
        return (
            "Dashed strokes are not reproduced. The stroke is drawn solid; "
            "use a Fusion Duplicate or Paint node to add dashes."
        )
    return None
