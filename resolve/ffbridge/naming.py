"""Fusion node naming.

Fusion tool names are identifiers, not labels: they must match
``[A-Za-z_][A-Za-z0-9_]*``, and they are how expressions and links refer to
nodes. Design layer names are none of those things — they contain spaces,
slashes, emoji, non-Latin scripts, and they repeat freely.

The mapping is designed so that a designer can still recognise their layers in
the node graph, which is most of the value of importing structure at all:

    "CTA Button"        -> CTA_Button_Shape, CTA_Button_Stroke, CTA_Button_Merge
    "Card / Header"     -> Card_Header_Shape
    "Заголовок"         -> Zagolovok_Text      (transliterated, not discarded)
    "🔥 Hot"            -> Hot_Shape
    ""                  -> Layer_Shape

Uniqueness is enforced by a numeric suffix that is stable for a given build
order, so re-running a transfer produces the same names and diffs stay readable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_RESERVED = {"Comp", "Composition", "Tools", "Input", "Output", "Instance"}


def _transliterate(text: str) -> str:
    """Best-effort ASCII fold that keeps names readable rather than blank.

    Latin accents decompose cleanly via NFKD. Cyrillic does not, so it gets an
    explicit table — dropping it would turn every layer in a Russian document
    into ``Layer_1``, ``Layer_2``, which defeats the purpose of importing names.
    """
    out = []
    for ch in text:
        low = ch.lower()
        if low in _CYRILLIC:
            mapped = _CYRILLIC[low]
            out.append(mapped.upper() if ch.isupper() and mapped else mapped)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        ascii_part = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(ascii_part if ascii_part.isascii() else " ")
    return "".join(out)


def sanitize(name: str, fallback: str = "Layer") -> str:
    """Turn a layer name into a legal Fusion identifier."""
    text = _transliterate(name or "")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")

    if not text:
        text = fallback
    if text[0].isdigit():
        text = "N" + text
    if text in _RESERVED:
        text = text + "_"
    # Fusion tolerates long names but the node graph becomes unreadable.
    return text[:48]


class NameAllocator:
    """Hands out unique Fusion tool names.

    Suffixes start at ``_2`` rather than ``_1`` so the first node of a given
    name keeps the clean form — matching how Fusion itself names duplicates.
    """

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}

    def allocate(self, base: str, role: Optional[str] = None, fallback: str = "Layer") -> str:
        stem = sanitize(base, fallback)
        if role:
            stem = f"{stem}_{sanitize(role, 'Node')}"
        stem = stem[:56]

        count = self._counts.get(stem, 0) + 1
        self._counts[stem] = count
        return stem if count == 1 else f"{stem}_{count}"

    def reserve(self, name: str) -> None:
        """Mark a name as taken, e.g. one already present in the user's comp."""
        self._counts[name] = max(self._counts.get(name, 0), 1)
