"""Bounded chunked world: up-front generation, Fields, halos, spatial entity index.

The :class:`World` is the top-level spatial container. It holds a bounded
``width_chunks`` × ``height_chunks`` grid of :class:`~.chunk.Chunk` objects, ALL
generated up front at construction (no lazy generation). Each chunk stores its
environmental state as ghost-padded struct-of-arrays
:class:`~.field.Field`s and a per-cell entity index. A ghost halo of width
``halo`` surrounds every chunk — across chunk seams and at the world edge — as
a read-only reflective mirror, refreshed by :meth:`refresh_halos`.

ECS seam (v1 = design-for, defer wiring):
    World is a self-contained, non-global object. A future engine integration
    will expose it on ``SystemContext`` (e.g. ``ctx.world``) and may pass the
    engine's shared RNG; this version keeps the World a pure function of its
    constructor args (``seed``-derived randomness, no global state) so it drops
    onto that seam without signature churn. The ``ecs/`` package is NOT modified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .biome import Biome
from .chunk import DEFAULT_CHUNK_SIZE, Chunk
from .coords import CellCoord, ChunkCoord
from .field import FIELD_SCHEMA

if TYPE_CHECKING:
    from population_engine.ecs.entity import Entity

__all__ = ["World"]


def _cantor(ix: int, iy: int) -> int:
    """Cantor pairing of two ints; stable across runs (no hash randomization)."""
    return (ix + iy) * (ix + iy + 1) // 2 + iy


class World:
    """A bounded M×N chunk grid with ghost-padded SoA fields and a spatial index.

    Parameters
    ----------
    seed:
        Master seed for deterministic generation. Combined with each chunk's
        coordinates to produce per-chunk sub-seeds (order-independent).
    width_chunks, height_chunks:
        Number of chunks along x and y (both >= 1). All are generated up front.
    chunk_size:
        Side-length of a chunk in cells (default 32).
    halo:
        Ghost-halo width around every chunk in cells (default 1).
    biomes:
        Ordered biome table used to classify generated cells. First match wins.
    """

    __slots__ = (
        "chunk_size",
        "halo",
        "width_chunks",
        "height_chunks",
        "_grid",
        "_seed",
        "_biomes",
    )

    def __init__(
        self,
        seed: int = 42,
        width_chunks: int = 8,
        height_chunks: int = 8,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        halo: int = 1,
        biomes: list[Biome] | None = None,
    ) -> None:
        for label, value in (
            ("width_chunks", width_chunks),
            ("height_chunks", height_chunks),
            ("chunk_size", chunk_size),
            ("halo", halo),
        ):
            if value < 1:
                raise ValueError(f"{label} must be >= 1, got {value}")

        self.chunk_size = chunk_size
        self.halo = halo
        self.width_chunks = width_chunks
        self.height_chunks = height_chunks
        self._seed = seed
        self._biomes: list[Biome] = list(biomes or [])

        # rows = iy (south), cols = ix (east); _grid[iy][ix] == Chunk(ChunkCoord(ix, iy)).
        self._grid: list[list[Chunk]] = [
            [None] * width_chunks for _ in range(height_chunks)
        ]
        for iy in range(height_chunks):
            for ix in range(width_chunks):
                self._grid[iy][ix] = self._generate_chunk(ChunkCoord(ix, iy))

        # Start stencil-ready: every chunk's halo mirrored from neighbours /
        # the reflective world edge. Idempotent w.r.t. interiors.
        self.refresh_halos()

    # -- biome table ------------------------------------------------------

    @property
    def biomes(self) -> tuple[Biome, ...]:
        """Immutable view of the biome table."""
        return tuple(self._biomes)

    def classify(self, altitude: float, temperature: float, humidity: float) -> int:
        """Index of the first matching biome, else ``0`` (unclassified/default).

        Reuses :meth:`Biome.matches`: inclusive-min / exclusive-max ranges,
        first match wins.
        """
        for i, biome in enumerate(self._biomes):
            if biome.matches(altitude, temperature, humidity):
                return i
        return 0

    def classify_chunk(self, chunk: Chunk) -> np.ndarray:
        """Vectorised biome ids (int64, ``chunk_size`` × ``chunk_size``).

        Mirrors :meth:`classify` for every interior cell of *chunk*, reading its
        altitude/temperature/humidity Fields.
        """
        return self._classify_array(
            chunk.field("altitude").interior,
            chunk.field("temperature").interior,
            chunk.field("humidity").interior,
        )

    def _classify_array(
        self,
        altitude: np.ndarray,
        temperature: np.ndarray,
        humidity: np.ndarray,
    ) -> np.ndarray:
        """First-match-wins classification into int64 ids (vectorised)."""
        out = np.zeros(altitude.shape, dtype=np.int64)
        matched = np.zeros(altitude.shape, dtype=bool)
        for i, b in enumerate(self._biomes):
            m = (~matched) & (
                (b.min_altitude <= altitude)
                & (altitude < b.max_altitude)
                & (b.min_temperature <= temperature)
                & (temperature < b.max_temperature)
                & (b.min_humidity <= humidity)
                & (humidity < b.max_humidity)
            )
            out[m] = i
            matched |= m
        return out

    # -- chunk management -------------------------------------------------

    def has_chunk(self, coord: ChunkCoord) -> bool:
        """True iff *coord* is within the bounded index range.

        All such chunks are always loaded, so 'has' is a pure bounds test.
        """
        return (
            0 <= coord.ix < self.width_chunks
            and 0 <= coord.iy < self.height_chunks
        )

    @property
    def loaded_chunks(self) -> int:
        """Total chunks in the world (``width_chunks * height_chunks``)."""
        return self.width_chunks * self.height_chunks

    def chunk(self, coord: ChunkCoord) -> Chunk:
        """Return the (pre-built) chunk at *coord*. ``IndexError`` if out of bounds."""
        self._require_chunk_bounds(coord)
        return self._grid[coord.iy][coord.ix]

    def _require_chunk_bounds(self, ck: ChunkCoord) -> None:
        if not (
            0 <= ck.ix < self.width_chunks
            and 0 <= ck.iy < self.height_chunks
        ):
            raise IndexError(
                f"chunk ({ck.ix}, {ck.iy}) out of world bounds "
                f"[0, {self.width_chunks}) × [0, {self.height_chunks})"
            )

    # -- field access ------------------------------------------------------

    def value(self, name: str, coord: CellCoord):
        """Read-only scalar value of field *name* at world *coord*.

        Returns a numpy scalar. ``KeyError`` if *name* is not a schema field,
        ``IndexError`` if *coord* is out of world bounds. To write a value,
        mutate the chunk's ``interior`` view via :meth:`chunk`.
        """
        ck = coord.to_chunk(self.chunk_size)
        self._require_chunk_bounds(ck)
        lx, ly = coord.local_offset(self.chunk_size)
        return self._grid[ck.iy][ck.ix].field(name).interior[ly, lx]

    # -- spatial entity queries -------------------------------------------

    def entities_at(self, coord: CellCoord) -> frozenset[Entity]:
        """Immutable snapshot of entities at world cell *coord*.

        Returns an empty :class:`frozenset` for an out-of-bounds coordinate.
        """
        ck = coord.to_chunk(self.chunk_size)
        if not (
            0 <= ck.ix < self.width_chunks
            and 0 <= ck.iy < self.height_chunks
        ):
            return frozenset()
        lx, ly = coord.local_offset(self.chunk_size)
        return self._grid[ck.iy][ck.ix].entities_at(lx, ly)

    def add_entity(self, entity: Entity, coord: CellCoord) -> None:
        """Register *entity* at world cell *coord*. ``IndexError`` if out of bounds."""
        ck = coord.to_chunk(self.chunk_size)
        self._require_chunk_bounds(ck)
        lx, ly = coord.local_offset(self.chunk_size)
        self._grid[ck.iy][ck.ix].add_entity(entity, lx, ly)

    def remove_entity(self, entity: Entity, coord: CellCoord) -> None:
        """Remove *entity* from world cell *coord*. ``IndexError`` if out of bounds."""
        ck = coord.to_chunk(self.chunk_size)
        self._require_chunk_bounds(ck)
        lx, ly = coord.local_offset(self.chunk_size)
        self._grid[ck.iy][ck.ix].remove_entity(entity, lx, ly)

    def move_entity(
        self,
        entity: Entity,
        from_coord: CellCoord,
        to_coord: CellCoord,
    ) -> None:
        """Move *entity* from one world cell to another (cross-chunk transparent).

        ``IndexError`` if either coordinate is out of world bounds.
        """
        from_ck = from_coord.to_chunk(self.chunk_size)
        to_ck = to_coord.to_chunk(self.chunk_size)
        self._require_chunk_bounds(from_ck)
        self._require_chunk_bounds(to_ck)
        src = self._grid[from_ck.iy][from_ck.ix]
        dst = self._grid[to_ck.iy][to_ck.ix]
        src.remove_entity(entity, *from_coord.local_offset(self.chunk_size))
        dst.add_entity(entity, *to_coord.local_offset(self.chunk_size))

    def clear_entity(self, entity: Entity) -> None:
        """Remove *entity* from every chunk in the world."""
        for row in self._grid:
            for chunk_obj in row:
                chunk_obj.clear_entity(entity)

    # -- halo refresh ------------------------------------------------------

    def refresh_halos(self) -> None:
        """Recompute every chunk's halo ring from neighbour / reflective-edge values.

        For each FieldSpec, the whole-world interior is assembled; each chunk's
        padded context is built by indexing it at the *clamped* world
        coordinates of every padded cell (world edges clamp to the boundary),
        and handed to :meth:`Field.fill_halo`. This yields a neighbour mirror
        across interior seams and a reflective (own-edge) mirror at the world
        boundary. Idempotent w.r.t. interiors; refreshes halos only.
        """
        S, h = self.chunk_size, self.halo
        H = self.height_chunks * S
        W = self.width_chunks * S
        for spec in FIELD_SCHEMA:
            whole = np.empty((H, W), dtype=spec.dtype)
            for iy in range(self.height_chunks):
                for ix in range(self.width_chunks):
                    whole[iy * S : (iy + 1) * S, ix * S : (ix + 1) * S] = (
                        self._grid[iy][ix].field(spec.name).interior
                    )
            for iy in range(self.height_chunks):
                for ix in range(self.width_chunks):
                    ox = ix * S
                    oy = iy * S
                    row_sel = np.clip(np.arange(oy - h, oy + S + h), 0, H - 1)
                    col_sel = np.clip(np.arange(ox - h, ox + S + h), 0, W - 1)
                    self._grid[iy][ix].field(spec.name).fill_halo(
                        whole[np.ix_(row_sel, col_sel)]
                    )

    # -- procedural generation --------------------------------------------

    def _generate_chunk(self, coord: ChunkCoord) -> Chunk:
        """Build one chunk's interior Fields from deterministic vectorised math.

        Each chunk gets a sub-seed derived from the master seed and its
        coordinates (Cantor pairing), so generation is reproducible regardless
        of access order. The recipe (radial-gradient mountain, lapse-rate
        temperature, altitude-correlated humidity) is preserved; only the
        per-cell loop is vectorised.
        """
        S = self.chunk_size
        chunk_seed = self._seed ^ _cantor(coord.ix, coord.iy)
        rng = np.random.default_rng(chunk_seed)
        origin = coord.cell_origin(S)

        ly, lx = np.meshgrid(np.arange(S), np.arange(S), indexing="ij")
        ax = origin.x + lx
        ay = origin.y + ly
        dist = np.sqrt(ax ** 2 + ay ** 2) * 25.0
        base = 3000.0 * np.exp(-dist / 7000.0)  # mountain core near world origin

        altitude = np.maximum(0.0, base + rng.normal(0.0, 200.0, size=(S, S)))
        altitude = altitude.astype(np.float64)
        temperature = np.maximum(
            0.0, 28.0 - altitude * 0.0065 + rng.normal(0.0, 1.5, size=(S, S))
        ).astype(np.float64)
        humidity = np.clip(
            0.7 - altitude * 8e-5 + rng.normal(0.0, 0.1, size=(S, S)), 0.0, 1.0
        ).astype(np.float64)
        biome_id = self._classify_array(altitude, temperature, humidity)

        return Chunk(
            coord=coord,
            chunk_size=S,
            halo=self.halo,
            fields={
                "altitude": altitude,
                "temperature": temperature,
                "humidity": humidity,
                "biome_id": biome_id,
            },
        )
