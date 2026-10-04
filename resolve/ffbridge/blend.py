"""Blend-mode mapping.

The Fusion ``ApplyMode`` identifiers below were read out of composition files
shipped by Blackmagic Design, not from documentation, because Fusion's naming is
not internally consistent and the inconsistency is invisible until it fails
silently: ``"Color Burn"`` has a space but ``"LinearBurn"`` does not,
``"Soft Light"`` has a space but ``"LighterColor"`` does not. An input set to an
unrecognised FuID keeps its default, so a wrong string produces a Normal merge
with no error anywhere.

Modes that Fusion cannot reproduce exactly are mapped to the closest available
operation and always paired with a diagnostic. Nothing is approximated silently.
"""

from __future__ import annotations

from typing import Dict, NamedTuple, Optional


class BlendMapping(NamedTuple):
    #: The Fusion ``ApplyMode`` FuID, or ``None`` for Normal (input left unset).
    apply_mode: Optional[str]
    #: True when the result is mathematically identical to the source tool.
    exact: bool
    #: Why it differs, when it does. Surfaced to the user verbatim.
    note: str = ""


#: Verified against shipped Blackmagic composition files.
_EXACT: Dict[str, str] = {
    "MULTIPLY": "Multiply",
    "SCREEN": "Screen",
    "OVERLAY": "Overlay",
    "DIFFERENCE": "Difference",
    "LIGHTEN": "Lighten",
    "COLOR_BURN": "Color Burn",
    "COLOR_DODGE": "Color Dodge",
    "HARD_LIGHT": "Hard Light",
    "SOFT_LIGHT": "Soft Light",
    "LINEAR_BURN": "LinearBurn",
}

#: Present in Fusion and semantically right, but the exact formula differs from
#: the design tool's, so the result can drift on extreme values.
_APPROXIMATE: Dict[str, tuple] = {
    "DARKEN": ("DarkerColor", "Fusion compares composite luminance; the design tool compares per channel."),
    "LINEAR_DODGE": ("LinearLight", "Mapped to Linear Light; Fusion has no separate Linear Dodge apply mode."),
    "EXCLUSION": ("Difference", "Fusion has no Exclusion apply mode; Difference is the nearest match."),
}

#: Non-separable modes. Fusion's Merge works per channel and cannot express
#: these; reproducing them needs a colour-space subgraph, which is out of scope
#: for a Merge-level mapping and is reported instead of faked.
_UNSUPPORTED = {
    "HUE": "Hue blending is not available as a Fusion apply mode.",
    "SATURATION": "Saturation blending is not available as a Fusion apply mode.",
    "COLOR": "Color blending is not available as a Fusion apply mode.",
    "LUMINOSITY": "Luminosity blending is not available as a Fusion apply mode.",
}


def map_blend_mode(mode: str) -> BlendMapping:
    """Map a design blend mode onto a Fusion ``ApplyMode``.

    ``PASS_THROUGH`` and ``NORMAL`` both become Normal: pass-through only has
    meaning for a group that is not isolated, and once a group is rebuilt as an
    explicit Merge chain the two are the same thing.
    """
    m = (mode or "NORMAL").upper()

    if m in ("NORMAL", "PASS_THROUGH"):
        return BlendMapping(None, True)
    if m in _EXACT:
        return BlendMapping(_EXACT[m], True)
    if m in _APPROXIMATE:
        fusion_mode, note = _APPROXIMATE[m]
        return BlendMapping(fusion_mode, False, note)
    if m in _UNSUPPORTED:
        return BlendMapping(None, False, _UNSUPPORTED[m] + " The layer is merged normally.")
    return BlendMapping(None, False, f'Unknown blend mode "{mode}". The layer is merged normally.')
