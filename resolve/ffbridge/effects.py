"""Effect conversion: shadows and blurs.

Two things here are genuinely lossy and both are handled by a single named
conversion function rather than by per-object tweaking, so that behaviour is
predictable and can be corrected in one place if visual regression testing shows
a systematic offset.

**Blur radius.** Design tools specify a blur by a CSS-style radius; the
underlying Gaussian has a standard deviation of roughly half that radius (the
convention CSS ``filter: blur()`` and SVG ``feGaussianBlur`` share is
``sigma = radius / 2``). Fusion's Blur node takes a *Blur Size*, which is
normalised against the image width rather than measured in pixels, so a size of
1.0 is a very large blur regardless of resolution. Converting therefore needs
both the sigma convention and the normalisation, and getting either wrong
produces a blur that looks right at 1080p and wrong at 4K.

**Shadow offset.** Design tools give a Cartesian offset. Fusion's Shadow node
takes the same, as ``ShadowOffset``, but in normalised image space with +Y up,
so the vertical component is negated. Converting to the distance/angle form some
compositors use is avoided entirely: it is undefined at zero offset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

#: Ratio between a CSS-style blur radius and the Gaussian standard deviation it
#: implies. Shared by CSS, SVG and every major design tool.
SIGMA_PER_RADIUS = 0.5

#: Fusion expresses Blur Size relative to the image width, and a Blur Size of
#: 1.0 corresponds to a Gaussian sigma of this many image widths. Derived from
#: Fusion's own normalisation, isolated here so a single number can be corrected
#: if the visual regression suite finds a systematic difference.
FUSION_BLUR_SIZE_PER_SIGMA_WIDTH = 10.0


def blur_radius_to_fusion_size(radius_px: float, comp_width: int) -> float:
    """Design blur radius (px) -> Fusion Blur ``XBlurSize``/``YBlurSize``.

    Resolution independent by construction: doubling the composition width while
    keeping the design scale doubles ``radius_px`` and leaves the returned size
    unchanged, which is what keeps a re-rendered 4K version looking like the
    1080p one.
    """
    if radius_px <= 0 or comp_width <= 0:
        return 0.0
    sigma_px = radius_px * SIGMA_PER_RADIUS
    sigma_norm = sigma_px / float(comp_width)
    return sigma_norm * FUSION_BLUR_SIZE_PER_SIGMA_WIDTH


def fusion_size_to_blur_radius(size: float, comp_width: int) -> float:
    """Inverse of :func:`blur_radius_to_fusion_size`, for round-trip tests."""
    if size <= 0 or comp_width <= 0:
        return 0.0
    sigma_norm = size / FUSION_BLUR_SIZE_PER_SIGMA_WIDTH
    return (sigma_norm * comp_width) / SIGMA_PER_RADIUS


@dataclass(frozen=True)
class ShadowParams:
    """Everything a Fusion ``Shadow`` node needs, already in Fusion units."""

    offset_x: float          # normalised image space, +X right
    offset_y: float          # normalised image space, +Y up
    softness: float          # Fusion Softness
    color: Tuple[float, float, float, float]
    #: Set when the design asked for something Fusion cannot do exactly.
    warning: str = ""


def drop_shadow_params(
    offset_px: Sequence[float],
    radius_px: float,
    spread_px: float,
    color: Sequence[float],
    comp_width: int,
    comp_height: int,
    scale: float = 1.0,
) -> ShadowParams:
    """Convert a drop shadow.

    ``spread`` has no Fusion equivalent — it dilates the shadow's matte before
    blurring, which the Shadow node cannot do. Rather than ignoring it, a
    non-zero spread is reported and partially compensated by widening the
    softness, which keeps the shadow's visual weight close even though its edge
    profile differs.
    """
    dx = float(offset_px[0]) * scale
    dy = float(offset_px[1]) * scale

    warning = ""
    softness = blur_radius_to_fusion_size(radius_px * scale, comp_width)

    if abs(spread_px) > 1e-6:
        warning = (
            "Shadow spread has no direct equivalent in Fusion. The shadow's "
            "softness was widened to compensate, so its edge will look slightly "
            "different from the design."
        )
        softness = blur_radius_to_fusion_size((radius_px + abs(spread_px)) * scale, comp_width)

    return ShadowParams(
        offset_x=dx / float(comp_width),
        # +Y is down in design space and up in Fusion.
        offset_y=-dy / float(comp_height),
        softness=softness,
        color=(float(color[0]), float(color[1]), float(color[2]), float(color[3]) if len(color) > 3 else 1.0),
        warning=warning,
    )


@dataclass(frozen=True)
class InnerShadowPlan:
    """The subgraph that reproduces an inner shadow.

    Fusion has no inner-shadow tool, but the effect is well defined and can be
    built exactly rather than approximated:

        1. Take the layer's own alpha as a matte.
        2. Invert it, so the *outside* of the shape becomes solid.
        3. Offset that inverted matte by the shadow offset and blur it.
        4. Intersect the result back with the original alpha, so the shadow
           only appears inside the shape.
        5. Tint it with the shadow colour and merge it over the layer.

    Steps 2-4 are what make it an *inner* shadow, and each maps onto a real
    Fusion tool, so the result is editable rather than baked.
    """

    offset_x: float
    offset_y: float
    softness: float
    color: Tuple[float, float, float, float]
    note: str = (
        "Inner shadow is built from a matte, blur and merge subgraph. Every step "
        "is editable, but very large blur radii can differ slightly from the design."
    )


def inner_shadow_plan(
    offset_px: Sequence[float],
    radius_px: float,
    spread_px: float,
    color: Sequence[float],
    comp_width: int,
    comp_height: int,
    scale: float = 1.0,
) -> InnerShadowPlan:
    base = drop_shadow_params(offset_px, radius_px, spread_px, color, comp_width, comp_height, scale)
    return InnerShadowPlan(
        # The matte is inverted, so the shadow must travel the opposite way for
        # the lit edge to land on the correct side of the shape.
        offset_x=-base.offset_x,
        offset_y=-base.offset_y,
        softness=base.softness,
        color=base.color,
    )


def background_blur_support_note() -> str:
    """Why background blur is Experimental, stated plainly."""
    return (
        "Background blur needs the layers behind this one, which means the node "
        "graph has to branch and re-merge. The result is built, but it can differ "
        "from the design where layers overlap in complex ways."
    )
