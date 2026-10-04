"""Node graph layout.

An imported graph that works but looks like spaghetti is a graph nobody will
animate. Layout is therefore part of the product, not a cosmetic afterthought.

The scheme is a spine and ribs. The composite chain runs left to right along a
single row — the spine — and every design layer contributes a rib above it,
built left to right in the order the pixels flow: shape, then fill and stroke
combination, then effects, then the user's animation Transform, then down into
the spine's Merge.

Rows are allocated top-down in the order layers are painted, so the vertical
order of ribs in the Fusion graph matches the layer order in the design tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

#: Fusion's own node spacing. Matches what the Fusion editor uses when it
#: auto-arranges, so an imported graph sits on the same grid as hand-built work.
COL = 110.0
ROW = 110.0  # Allow room for expanded Loader/Background thumbnails.


@dataclass
class GraphLayout:
    """Allocates positions for a spine-and-ribs graph."""

    spine_row: float = 0.0
    _spine_col: int = 0
    _rib_row: int = 0
    _rib_cols: Dict[int, int] = field(default_factory=dict)

    def next_spine(self) -> Tuple[float, float]:
        """The next position along the composite chain."""
        pos = (self._spine_col * COL, self.spine_row * ROW)
        self._spine_col += 1
        return pos

    def new_rib(self) -> int:
        """Start a new branch. Returns a handle for :meth:`rib_step`."""
        self._rib_row -= 1
        self._rib_cols[self._rib_row] = 0
        return self._rib_row

    def rib_step(self, rib: int) -> Tuple[float, float]:
        """The next position along a branch."""
        col = self._rib_cols.get(rib, 0)
        self._rib_cols[rib] = col + 1
        return (col * COL, rib * ROW)

    def align_rib_to_spine(self, rib: int) -> None:
        """Push a branch rightwards so it ends where its Merge sits.

        Without this, deep branches run past the Merge they feed and the wires
        double back on themselves, which is exactly the look this layout exists
        to avoid.
        """
        used = self._rib_cols.get(rib, 0)
        if used < self._spine_col:
            self._rib_cols[rib] = self._spine_col
