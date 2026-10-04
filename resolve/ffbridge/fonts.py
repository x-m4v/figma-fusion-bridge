"""Font resolution.

Rule: a missing font is reported, never silently substituted. Swapping a
typeface changes the design, and a designer who is not told will find out at the
worst possible moment.

Resolution works down a ladder of decreasing confidence, and the confidence is
carried in the result so the UI can distinguish "found it" from "guessed":

    1. Exact family + exact style          -> EXACT
    2. Exact family, style matched by
       weight and slant                    -> STYLE_APPROXIMATED
    3. Exact family, any style             -> STYLE_FALLBACK
    4. No family match                     -> MISSING

Nothing here writes a substitution into the graph on its own. The caller decides
what to do with a ``MISSING`` result, and the default is to keep the original
name in the Text+ node so the user can install the font and have it appear —
rather than baking in a substitute that has to be undone by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

EXACT = "EXACT"
STYLE_APPROXIMATED = "STYLE_APPROXIMATED"
STYLE_FALLBACK = "STYLE_FALLBACK"
MISSING = "MISSING"

#: Common style-name vocabulary mapped to a numeric weight.
_WEIGHT_WORDS: Sequence[Tuple[str, int]] = (
    ("extrablack", 950), ("ultrablack", 950),
    ("black", 900), ("heavy", 900),
    ("extrabold", 800), ("ultrabold", 800),
    ("semibold", 600), ("demibold", 600),
    ("bold", 700),
    ("medium", 500),
    ("regular", 400), ("normal", 400), ("book", 400), ("roman", 400),
    ("light", 300),
    ("extralight", 200), ("ultralight", 200),
    ("thin", 100), ("hairline", 100),
)


def weight_from_style(style: str) -> int:
    """Infer a numeric weight from a style name.

    Ordered longest-first so that "extrabold" is not matched as "bold" and
    "semibold" is not matched as "bold" either — a mistake that turns a 600 into
    a 700 and is easy to miss visually.
    """
    s = re.sub(r"[^a-z]", "", (style or "").lower())
    for word, weight in sorted(_WEIGHT_WORDS, key=lambda w: -len(w[0])):
        if word in s:
            return weight
    return 400


def is_italic(style: str) -> bool:
    s = (style or "").lower()
    return "italic" in s or "oblique" in s


@dataclass
class FontMatch:
    family: str
    style: str
    confidence: str
    requested_family: str = ""
    requested_style: str = ""
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.confidence == EXACT


@dataclass
class FontResolver:
    """Matches requested fonts against the fonts available on this machine.

    The catalogue is injected rather than discovered inside this class so the
    matching logic is testable without depending on what happens to be
    installed. :func:`system_font_catalogue` supplies the real one.
    """

    #: family (lowercased) -> list of available style names
    catalogue: Dict[str, List[str]] = field(default_factory=dict)

    def resolve(self, family: str, style: str, post_script_name: str = "") -> FontMatch:
        fam_key = (family or "").strip().lower()
        styles = self.catalogue.get(fam_key)

        if styles is None:
            return FontMatch(
                family=family,
                style=style,
                confidence=MISSING,
                requested_family=family,
                requested_style=style,
                note=(
                    f'The font "{family} {style}" is not installed on this Mac. '
                    "Text is created with the original font name, so installing the "
                    "font makes it appear correctly without re-importing."
                ),
            )

        # 1. Exact style.
        for s in styles:
            if s.strip().lower() == (style or "").strip().lower():
                return FontMatch(family, s, EXACT, family, style)

        # 2. Same weight and slant.
        want_w, want_i = weight_from_style(style), is_italic(style)
        for s in styles:
            if weight_from_style(s) == want_w and is_italic(s) == want_i:
                return FontMatch(
                    family, s, STYLE_APPROXIMATED, family, style,
                    note=f'Style "{style}" was matched to "{s}" (same weight).',
                )

        # 3. Nearest weight with the right slant, else nearest weight.
        same_slant = [s for s in styles if is_italic(s) == want_i] or list(styles)
        best = min(same_slant, key=lambda s: abs(weight_from_style(s) - want_w))
        return FontMatch(
            family, best, STYLE_FALLBACK, family, style,
            note=(
                f'The font family "{family}" is installed but not the "{style}" style. '
                f'"{best}" is the closest available weight.'
            ),
        )


def system_font_catalogue(use_cache: bool = True) -> Dict[str, List[str]]:
    """Enumerate installed font families on macOS.

    Delegates to :mod:`ffbridge.macfonts`, which reads CoreText directly. An
    empty catalogue degrades to "report every font as missing", which is the
    honest failure mode: the alternative would be to claim fonts resolved when
    we never actually checked.
    """
    import sys
    if sys.platform == "win32":
        from .winfonts import enumerate_fonts
    else:
        from .macfonts import enumerate_fonts

    return enumerate_fonts(use_cache=use_cache)
