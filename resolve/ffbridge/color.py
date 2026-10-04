"""Colour conversion.

Design tools hand out sRGB values with the sRGB transfer function already
applied (what a CSS ``#RRGGBB`` means). DaVinci Resolve may be running the
timeline in Rec.709, DaVinci Wide Gamut, ACES or an HDR space, and a Fusion
composition inherits that. So the RGB numbers from the design tool are *not*
unconditionally the RGB numbers Fusion should receive, and assuming they are is
how a brand colour arrives visibly wrong.

Three policies are offered, and which one is right depends on the project, so
the tool asks rather than guesses:

``MATCH_SRGB``
    Pass encoded values through untouched for source-graphics compositing.
    The Receive pipeline adds an explicit working-space boundary afterwards.
    Passthrough alone does not guarantee display or output matching.

``PROJECT_MANAGED``
    Legacy utility: linearise with the sRGB EOTF only. This does NOT convert
    primaries and is insufficient for DWG or ACES. Receive does not use it.

``ADVANCED``
    Legacy alias for sRGB linearisation; no gamut conversion is performed.
    Use color_pipeline for the supported explicit Receive conversions.

Alpha is never transformed. It is not a colour.
"""

from __future__ import annotations

from typing import Sequence, Tuple

RGBA = Tuple[float, float, float, float]

MATCH_SRGB = "MATCH_SRGB"
PROJECT_MANAGED = "PROJECT_MANAGED"
ADVANCED = "ADVANCED"


def srgb_to_linear(c: float) -> float:
    """Exact sRGB EOTF (IEC 61966-2-1), not the 2.2 power approximation.

    The approximation is off by up to ~0.5% in the shadows, which is visible as
    a colour shift on dark UI surfaces — exactly the material this tool moves.
    Values outside 0..1 are passed through the linear segment so that
    out-of-range colours stay monotonic instead of folding back.
    """
    if c < 0.0:
        return -srgb_to_linear(-c)
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    """Inverse of :func:`srgb_to_linear`."""
    if c < 0.0:
        return -linear_to_srgb(-c)
    if c <= 0.0031308:
        return c * 12.92
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def convert_rgba(rgba: Sequence[float], policy: str = MATCH_SRGB) -> RGBA:
    """Apply a colour policy to a non-premultiplied RGBA tuple."""
    r, g, b = float(rgba[0]), float(rgba[1]), float(rgba[2])
    a = float(rgba[3]) if len(rgba) > 3 else 1.0

    if policy == MATCH_SRGB:
        return (r, g, b, a)
    if policy in (PROJECT_MANAGED, ADVANCED):
        return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), a)
    raise ValueError(f"Unknown colour policy {policy!r}")


def multiply_alpha(rgba: Sequence[float], factor: float) -> RGBA:
    """Scale only the alpha channel.

    Used to fold a *paint's* opacity into its colour while leaving the layer's
    own opacity to a separate Merge — the two must stay independent.
    """
    return (float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]) * factor)


def premultiply(rgba: Sequence[float]) -> RGBA:
    """Straight -> premultiplied.

    Fusion composites premultiplied. Feeding straight-alpha colour into a Merge
    is what produces bright fringes around semi-transparent edges, so the
    conversion is explicit and named rather than implied.
    """
    r, g, b, a = rgba[0], rgba[1], rgba[2], rgba[3]
    return (r * a, g * a, b * a, a)


def unpremultiply(rgba: Sequence[float]) -> RGBA:
    """Premultiplied -> straight, guarding the divide-by-zero at fully transparent."""
    r, g, b, a = rgba[0], rgba[1], rgba[2], rgba[3]
    if a <= 1e-9:
        return (0.0, 0.0, 0.0, 0.0)
    return (r / a, g / a, b / a, a)


def to_hex(rgba: Sequence[float]) -> str:
    """Debug/logging helper. Clamps, because logs should never raise."""
    def ch(v: float) -> int:
        return max(0, min(255, int(round(v * 255.0))))

    return "#{:02X}{:02X}{:02X}{:02X}".format(ch(rgba[0]), ch(rgba[1]), ch(rgba[2]), ch(rgba[3] if len(rgba) > 3 else 1.0))
