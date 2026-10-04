"""Coordinate conversion between design space and Fusion space.

This module exists on its own because a sign error here is the single most
expensive kind of bug in a tool like this: everything still imports, the graph
still builds, and the result is quietly wrong by a few hundred pixels.

Three coordinate spaces are involved.

**Design space** — what the producer sends. Origin top-left of the document,
+X right, +Y **down**, units are design pixels. Figma, Sketch, Illustrator and
SVG all agree on this.

**Fusion image space** — used by ``Transform.Center``, ``Merge.Center``,
``Background.Start``/``End`` and the mask ``Center`` inputs. Each axis is
normalised independently against the composition's own width and height, so
(0, 0) is the bottom-left corner, (1, 1) the top-right and (0.5, 0.5) the
centre. +Y points **up**.

**Fusion shape space** — used by ``sRectangle``, ``sEllipse``, ``sNGon`` and the
rest of the ``s*`` family. The origin is the centre of the canvas and the unit
is the composition *height*, uniformly on both axes, so a shape stays square
when the composition is not. On a 1920x1080 comp the visible region is
x in [-0.888.., 0.888..] and y in [-0.5, 0.5]. Uniformity is what keeps vector
shapes resolution-independent: change the comp to 3840x2160 and every shape
lands in exactly the same place at twice the pixel size.

The shape-space unit convention is the one item that could not be confirmed by
static inspection (see FEASIBILITY.md §7.3). ``ShapeSpaceConvention`` makes it a
single switch rather than an assumption sprinkled through the builder, and the
bundled probe script rewrites it from a live Fusion session.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Tuple

Matrix = Sequence[Sequence[float]]  # [[a, c, e], [b, d, f]]

IDENTITY: Tuple[Tuple[float, float, float], Tuple[float, float, float]] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
)


# --------------------------------------------------------------------------
# Affine matrix helpers
# --------------------------------------------------------------------------

def mat_apply(m: Matrix, x: float, y: float) -> Tuple[float, float]:
    """Apply a 2x3 affine matrix to a point."""
    a, c, e = m[0]
    b, d, f = m[1]
    return (a * x + c * y + e, b * x + d * y + f)


def mat_mul(m1: Matrix, m2: Matrix) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Compose two affine matrices: the result applies ``m2`` then ``m1``."""
    a1, c1, e1 = m1[0]
    b1, d1, f1 = m1[1]
    a2, c2, e2 = m2[0]
    b2, d2, f2 = m2[1]
    return (
        (a1 * a2 + c1 * b2, a1 * c2 + c1 * d2, a1 * e2 + c1 * f2 + e1),
        (b1 * a2 + d1 * b2, b1 * c2 + d1 * d2, b1 * e2 + d1 * f2 + f1),
    )


def mat_invert(m: Matrix):
    """Invert a 2x3 affine matrix.

    Raises on a singular matrix rather than returning identity: a degenerate
    gradient transform is a real problem in the source document and the caller
    must turn it into a diagnostic, not paper over it.
    """
    a, c, e = m[0]
    b, d, f = m[1]
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("Singular affine matrix cannot be inverted")
    ia, ib = d / det, -b / det
    ic, id_ = -c / det, a / det
    ie = -(ia * e + ic * f)
    if_ = -(ib * e + id_ * f)
    return ((ia, ic, ie), (ib, id_, if_))


@dataclass(frozen=True)
class Decomposed:
    """An affine matrix split into the parts a compositor can consume."""

    translate_x: float
    translate_y: float
    scale_x: float
    scale_y: float
    #: Rotation in degrees, counter-clockwise positive, measured in *design*
    #: space where +Y is down. Convert with :meth:`CoordinateMapper.angle_to_fusion`.
    rotation_deg: float
    #: Shear as the angle in degrees between the transformed axes minus 90.
    skew_deg: float

    @property
    def is_uniform(self) -> bool:
        return abs(self.scale_x - self.scale_y) < 1e-9

    @property
    def has_skew(self) -> bool:
        return abs(self.skew_deg) > 1e-6


def decompose(m: Matrix) -> Decomposed:
    """QR-style decomposition into translate / rotate / scale / skew.

    Handles mirroring (negative determinant) by folding the flip into
    ``scale_y``, which keeps ``rotation_deg`` continuous instead of jumping by
    180 degrees as a naive ``atan2`` decomposition does.
    """
    a, c, e = m[0]
    b, d, f = m[1]

    scale_x = math.hypot(a, b)
    if scale_x == 0.0:
        return Decomposed(e, f, 0.0, math.hypot(c, d), 0.0, 0.0)

    # Normalised first basis vector gives the rotation.
    rot = math.atan2(b, a)
    # Shear is the projection of the second basis vector onto the first.
    shear = (a * c + b * d) / (scale_x * scale_x)
    # Remove the shear component to get the true second-axis scale.
    scale_y = math.hypot(c - shear * a, d - shear * b)

    det = a * d - b * c
    if det < 0:
        scale_y = -scale_y

    return Decomposed(
        translate_x=e,
        translate_y=f,
        scale_x=scale_x,
        scale_y=scale_y,
        rotation_deg=math.degrees(rot),
        skew_deg=math.degrees(math.atan(shear)),
    )


# --------------------------------------------------------------------------
# The mapper
# --------------------------------------------------------------------------

SHAPE_UNIT_HEIGHT = "height"
SHAPE_UNIT_WIDTH = "width"


@dataclass(frozen=True)
class CoordinateMapper:
    """Maps design pixels into a specific Fusion composition.

    ``origin_x`` / ``origin_y`` are subtracted first. They carry the top-left of
    the transferred selection in document coordinates, so a frame sitting at
    x=48000 on a large page lands in the middle of the comp instead of far
    off-screen.
    """

    comp_width: int
    comp_height: int
    origin_x: float = 0.0
    origin_y: float = 0.0
    #: Design pixels per composition pixel. 1.0 means a 1080-tall design fills a
    #: 1080-tall comp. Set by the caller when the user scales a design to fit.
    scale: float = 1.0
    shape_unit: str = SHAPE_UNIT_HEIGHT

    # -- image space -------------------------------------------------------

    @property
    def aspect(self) -> float:
        return self.comp_width / self.comp_height

    def to_comp_px(self, x: float, y: float) -> Tuple[float, float]:
        """Design point -> composition pixels, still top-left origin, +Y down."""
        return ((x - self.origin_x) * self.scale, (y - self.origin_y) * self.scale)

    def to_image_space(self, x: float, y: float) -> Tuple[float, float]:
        """Design point -> Fusion image space (0..1 per axis, +Y up)."""
        px, py = self.to_comp_px(x, y)
        return (px / self.comp_width, 1.0 - (py / self.comp_height))

    def size_to_image_space(self, w: float, h: float) -> Tuple[float, float]:
        """Design size -> image-space fractions. No Y flip: a size has no origin."""
        return ((w * self.scale) / self.comp_width, (h * self.scale) / self.comp_height)

    # -- shape space -------------------------------------------------------

    @property
    def _shape_divisor(self) -> float:
        return float(self.comp_height if self.shape_unit == SHAPE_UNIT_HEIGHT else self.comp_width)

    def to_shape_space(self, x: float, y: float) -> Tuple[float, float]:
        """Design point -> Fusion shape space (centre origin, uniform unit, +Y up)."""
        px, py = self.to_comp_px(x, y)
        div = self._shape_divisor
        return ((px - self.comp_width / 2.0) / div, (self.comp_height / 2.0 - py) / div)

    def length_to_shape_space(self, length: float) -> float:
        """Design length -> shape-space length. Uniform, so one scalar suffices."""
        return (length * self.scale) / self._shape_divisor

    # -- angles ------------------------------------------------------------

    @staticmethod
    def angle_to_fusion(design_degrees: float) -> float:
        """Design rotation -> Fusion rotation.

        Design space has +Y down, Fusion has +Y up, so a rotation that looks
        clockwise in the design tool is counter-clockwise in Fusion. The sign
        flip is the whole conversion, but forgetting it mirrors every rotated
        layer, so it lives in a named function that tests can pin.
        """
        return -design_degrees

    @staticmethod
    def normalize_angle(degrees: float) -> float:
        """Fold an angle into (-180, 180] so comparisons and UI stay sane."""
        a = math.fmod(degrees, 360.0)
        if a > 180.0:
            a -= 360.0
        elif a <= -180.0:
            a += 360.0
        return 0.0 if a == 0.0 else a


def mapper_for(
    comp_width: int,
    comp_height: int,
    frame_x: float = 0.0,
    frame_y: float = 0.0,
    frame_width: float = 0.0,
    frame_height: float = 0.0,
    fit: bool = False,
) -> CoordinateMapper:
    """Build a mapper for a transfer.

    With ``fit=False`` (the default) design pixels map 1:1 onto comp pixels and
    the design is centred, which is what a motion designer expects when the
    Figma frame and the timeline share a resolution.

    With ``fit=True`` the design is uniformly scaled to fit — uniformly, so the
    aspect ratio is never distorted.
    """
    scale = 1.0
    if fit and frame_width > 0 and frame_height > 0:
        scale = min(comp_width / frame_width, comp_height / frame_height)

    # Centre the (possibly scaled) design in the comp by shifting the origin.
    ox, oy = frame_x, frame_y
    if frame_width > 0 and frame_height > 0:
        ox -= (comp_width / scale - frame_width) / 2.0
        oy -= (comp_height / scale - frame_height) / 2.0

    return CoordinateMapper(
        comp_width=comp_width,
        comp_height=comp_height,
        origin_x=ox,
        origin_y=oy,
        scale=scale,
    )
