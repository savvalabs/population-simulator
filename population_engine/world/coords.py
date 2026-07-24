"""Coordinate types for the chunked world grid.

Every position in the world is identified by a :class:`CellCoord` — an absolute
(x, y) cell coordinate. The world is partitioned into fixed-size square
*chunks*, each addressed by a :class:`ChunkCoord`. The two coordinate spaces
are related by simple floor-division arithmetic given a ``chunk_size``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chunk import Chunk

__all__ = ["CellCoord", "ChunkCoord"]


@dataclass(frozen=True, slots=True, order=True)
class CellCoord:
    """Absolute cell coordinate in the world grid.

    ``(0, 0)`` is the origin (top-left of chunk (0, 0)). x increases to the
    right, y increases downward.
    """

    x: int
    y: int

    # -- chunk / local decomposition --------------------------------------

    def to_chunk(self, chunk_size: int) -> "ChunkCoord":
        """Return the chunk that contains this cell."""
        return ChunkCoord(
            ix=self.x // chunk_size,
            iy=self.y // chunk_size,
        )

    def local_offset(self, chunk_size: int) -> tuple[int, int]:
        """Return the (lx, ly) position within the containing chunk (0-based)."""
        return (self.x % chunk_size, self.y % chunk_size)


@dataclass(frozen=True, slots=True, order=True)
class ChunkCoord:
    """Chunk address in the chunk grid.

    Each chunk spans ``chunk_size`` × ``chunk_size`` cells. Chunk (0, 0)
    covers cells (0..chunk_size-1, 0..chunk_size-1).
    """

    ix: int
    iy: int

    # -- cell space -------------------------------------------------------

    def cell_origin(self, chunk_size: int) -> CellCoord:
        """Return the top-left cell coordinate of this chunk."""
        return CellCoord(x=self.ix * chunk_size, y=self.iy * chunk_size)

    def cell_range(self, chunk_size: int) -> tuple[CellCoord, CellCoord]:
        """Return (min, max_exclusive) cell coordinates for this chunk."""
        ox = self.ix * chunk_size
        oy = self.iy * chunk_size
        return (CellCoord(x=ox, y=oy), CellCoord(x=ox + chunk_size, y=oy + chunk_size))