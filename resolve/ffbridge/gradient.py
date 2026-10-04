"""Gradient conversion — design gradient transform to Fusion ``Background``.

Gradients arrive as a matrix, not as an angle. That is deliberate on the design
tool's side and worth preserving: an angle plus a length cannot express a
non-uniform or sheared gradient, and rounding to an angle early is a silent
quality loss on any layer that was scaled non-uniformly.

The unit gradient runs from (0, 0.5) to (1, 0.5) in *gradient space*.
``gradientTransform`` maps **object space to gradient space**, so recovering the
handles in object space means inverting it:

    inverse = invert(gradientTransform)
    start = inverse * (0, 0.5)      # first stop
    end   = inverse * (1, 0.5)      # last stop
    width = inverse * (0, 1)        # perpendicular extent, radial minor axis

Those three points are exactly what the design tool's REST API exposes as
``gradientHandlePositions``, which is a useful independent confirmation that the
inversion is the right way round.

The results are in normalised object space (0..1 across the node's box); the
caller turns them into design pixels and then into Fusion image space.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .coordinate import Matrix, mat_apply, mat_invert

#: Fusion ``GradientType`` FuID values, confirmed in shipped Blackmagic content
#: ("Reflect", "Square", "Cross" observed directly; "Linear", "Radial", "Angle"
#: are the remaining members of the same enum).
FUSION_LINEAR = "Linear"
FUSION_RADIAL = "Radial"
FUSION_ANGLE = "Angle"
FUSION_SQUARE = "Square"
FUSION_CROSS = "Cross"
FUSION_REFLECT = "Reflect"


@dataclass(frozen=True)
class GradientGeometry:
    """Gradient handles in normalised object space (0..1 across the node box)."""

    start: Tuple[float, float]
    end: Tuple[float, float]
    width: Tuple[float, float]

    @property
    def angle_degrees(self) -> float:
        """Angle of the gradient axis in design space, +Y down, degrees.

        0 points right, 90 points *down*. Reported for logging and for the UI;
        the builder itself uses the endpoints so that skew survives.
        """
        import math

        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.degrees(math.atan2(dy, dx))

    @property
    def length(self) -> float:
        import math

        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


def geometry_from_transform(transform: Matrix) -> GradientGeometry:
    """Recover gradient handles from a gradient transform matrix."""
    inv = mat_invert(transform)
    return GradientGeometry(
        start=mat_apply(inv, 0.0, 0.5),
        end=mat_apply(inv, 1.0, 0.5),
        width=mat_apply(inv, 0.0, 1.0),
    )


def geometry_from_handles(
    start: Sequence[float], end: Sequence[float], width: Optional[Sequence[float]] = None
) -> GradientGeometry:
    """Build geometry from pre-computed handles supplied by the producer."""
    w = tuple(width) if width is not None else (start[0], start[1] + 1.0)
    return GradientGeometry(
        start=(float(start[0]), float(start[1])),
        end=(float(end[0]), float(end[1])),
        width=(float(w[0]), float(w[1])),
    )


@dataclass(frozen=True)
class FusionGradientType:
    fu_id: str
    exact: bool
    note: str = ""


def map_gradient_type(paint_type: str) -> FusionGradientType:
    """Map a design gradient kind onto a Fusion ``GradientType``."""
    t = paint_type.upper()
    if t == "GRADIENT_LINEAR":
        return FusionGradientType(FUSION_LINEAR, True)
    if t == "GRADIENT_RADIAL":
        return FusionGradientType(FUSION_RADIAL, True)
    if t == "GRADIENT_ANGULAR":
        return FusionGradientType(
            FUSION_ANGLE,
            False,
            "Fusion's Angle gradient sweeps from the start point; the first and "
            "last stop may meet at a different angle than in the design.",
        )
    if t == "GRADIENT_DIAMOND":
        return FusionGradientType(
            FUSION_SQUARE,
            False,
            "Fusion has no diamond gradient. A square gradient is used, oriented "
            "along the same axis; the corners will differ.",
        )
    return FusionGradientType(FUSION_LINEAR, False, f'Unknown gradient type "{paint_type}".')


def build_stops(
    stops: Sequence[dict],
    paint_opacity: float = 1.0,
    color_policy: str = "MATCH_SRGB",
) -> List[Tuple[float, Tuple[float, float, float, float]]]:
    """Convert design gradient stops into Fusion ``Gradient`` stops.

    Every stop keeps its own alpha — the whole point of not rasterising — and
    the paint's own opacity is folded into those alphas here, because a Fusion
    ``Background`` has no separate paint-opacity control. The *layer's* opacity
    is deliberately not folded in; that stays on the Merge.

    Duplicate positions are nudged apart by a negligible epsilon. Fusion keys
    the stop table by position, so two stops at exactly the same position would
    collapse into one and quietly drop a hard colour break.
    """
    from .color import convert_rgba, multiply_alpha

    out: List[Tuple[float, Tuple[float, float, float, float]]] = []
    seen = set()
    for s in sorted(stops, key=lambda x: float(x.get("position", 0.0))):
        pos = float(s.get("position", 0.0))
        while pos in seen:
            pos += 1e-6
        seen.add(pos)
        c = s.get("color", {}) or {}
        rgba = (
            float(c.get("r", 0.0)),
            float(c.get("g", 0.0)),
            float(c.get("b", 0.0)),
            float(c.get("a", 1.0)),
        )
        rgba = convert_rgba(rgba, color_policy)
        rgba = multiply_alpha(rgba, paint_opacity)
        out.append((pos, rgba))

    if not out:
        out = [(0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0))]
    elif len(out) == 1:
        # A one-stop gradient is a solid colour; Fusion needs two to render it.
        out.append((1.0, out[0][1]))
    return out
