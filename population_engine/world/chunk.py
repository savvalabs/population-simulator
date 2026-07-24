"""Chunk: a fixed-size square grid of Fields with per-cell entity indexing.

A :class:`Chunk` is the unit of spatial storage. The world is a grid of
chunks, each spanning ``chunk_size`` × ``chunk_size`` cells. Environmental
state is struct-of-arrays: one :class:`~population_engine.world.field.Field`
per quantity, built from the canonical
:data:`~population_engine.world.field.FIELD_SCHEMA`. The chunk additionally
tracks which entities reside at each local cell offset, enabling fast
positional queries without scanning the full ECS registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .field import DEFAULT_HALO, FIELD_NAMES, FIELD_SCHEMA, Field

if TYPE_CHECKING:
    from population_engine.ecs.entity import Entity

from .coords import ChunkCoord

__all__ = ["Chunk", "DEFAULT_CHUNK_SIZE"]

#: Default side-length of a chunk in cells.
DEFAULT_CHUNK_SIZE: int = 32


class Chunk:
    """A square grid of ghost-padded Fields plus a per-cell entity index.

    Each :class:`~.field.FieldSpec` in
    :data:`~.field.FIELD_SCHEMA` becomes one :class:`~.field.Field`; all
    canonical fields are always present. The occupancy index is separate sparse
    dict-of-sets storage (it is sparse and entity-typed, not a numeric grid
    quantity, so it is deliberately not a Field).
    """

    __slots__ = ("coord", "chunk_size", "halo", "_fields", "_entity_index")

    def __init__(
        self,
        coord: "ChunkCoord",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        halo: int = DEFAULT_HALO,
        *,
        fields: dict[str, np.ndarray] | None = None,
    ) -> None:
        """Build a chunk from the schema, pre-filled where *fields* supplies interiors.

        For every FieldSpec in FIELD_SCHEMA, a :class:`Field` is constructed.
        If *fields* supplies *spec.name*, that S×S array seeds the field's
        interior (shape/dtype validated by :class:`Field`); otherwise the field
        is filled with ``spec.default``. Keys in *fields* not present in the
        schema raise ``KeyError`` (catches typos at construction).
        """
        self.coord = coord
        self.chunk_size = chunk_size
        self.halo = halo
        self._entity_index: dict[tuple[int, int], set[Entity]] = {}
        self._fields: dict[str, Field] = {}

        incoming = fields or {}
        for spec in FIELD_SCHEMA:
            self._fields[spec.name] = Field(
                spec.name,
                spec.dtype,
                chunk_size,
                halo,
                interior=incoming.get(spec.name),
                default=spec.default,
            )
        for name in incoming:
            if name not in self._fields:
                raise KeyError(f"unknown field {name!r} (not in FIELD_SCHEMA)")

    # -- fields -----------------------------------------------------------

    @property
    def cell_count(self) -> int:
        """Total number of interior cells (``chunk_size * chunk_size``)."""
        return self.chunk_size * self.chunk_size

    @property
    def field_names(self) -> tuple[str, ...]:
        """The canonical field names, in stable schema order."""
        return FIELD_NAMES

    def field(self, name: str) -> Field:
        """Return the named Field. ``KeyError`` if *name* is not in the schema."""
        try:
            return self._fields[name]
        except KeyError:
            raise KeyError(f"unknown field {name!r} (not in FIELD_SCHEMA)") from None

    # -- entity index -----------------------------------------------------

    def entities_at(self, lx: int, ly: int) -> frozenset[Entity]:
        """Immutable snapshot of entities at local cell *(lx, ly)*."""
        return frozenset(self._entity_index.get((lx, ly), ()))

    def add_entity(self, entity: Entity, lx: int, ly: int) -> None:
        """Register *entity* as present at local cell *(lx, ly)*.

        Coordinates are not range-checked (matches the original contract); the
        World enforces world bounds at its layer.
        """
        key = (lx, ly)
        self._entity_index.setdefault(key, set()).add(entity)

    def remove_entity(self, entity: Entity, lx: int, ly: int) -> None:
        """Remove *entity* from local cell *(lx, ly)*.

        ``KeyError`` if the cell was never indexed; ``set.discard`` is silent
        for an entity not present; emptied entries are pruned.
        """
        key = (lx, ly)
        slot = self._entity_index.get(key)
        if slot is None:
            raise KeyError(f"no entity index for local cell ({lx}, {ly})")
        slot.discard(entity)
        if not slot:
            del self._entity_index[key]

    def move_entity(
        self,
        entity: Entity,
        from_lx: int,
        from_ly: int,
        to_lx: int,
        to_ly: int,
    ) -> None:
        """Move *entity* from one local cell to another (intra-chunk)."""
        self.remove_entity(entity, from_lx, from_ly)
        self.add_entity(entity, to_lx, to_ly)

    def clear_entity(self, entity: Entity) -> None:
        """Remove *entity* from every cell in this chunk (bulk cleanup)."""
        for key, slot in list(self._entity_index.items()):
            slot.discard(entity)
            if not slot:
                del self._entity_index[key]

    @property
    def inhabited_cells(self) -> int:
        """Number of distinct local cells that have at least one entity."""
        return len(self._entity_index)
