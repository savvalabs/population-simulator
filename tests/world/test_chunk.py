"""Tests for :mod:`population_engine.world.chunk`."""

from __future__ import annotations

import numpy as np
import pytest

from population_engine.ecs.entity import Entity, EntityAllocator
from population_engine.world.chunk import DEFAULT_CHUNK_SIZE, Chunk
from population_engine.world.coords import ChunkCoord
from population_engine.world.field import DEFAULT_HALO, FIELD_NAMES, Field


_ALLOC = EntityAllocator()


def _mock_entity() -> Entity:
    """A dummy :class:`Entity` with a unique identity (no registry backing needed)."""
    return _ALLOC.allocate()


# -- construction ----------------------------------------------------------


def test_chunk_default_construction() -> None:
    c = Chunk(ChunkCoord(0, 0))
    assert c.coord == ChunkCoord(0, 0)
    assert c.chunk_size == DEFAULT_CHUNK_SIZE
    assert c.halo == DEFAULT_HALO
    assert c.cell_count == 32 * 32
    assert c.field_names == FIELD_NAMES


def test_chunk_with_custom_size_and_halo() -> None:
    c = Chunk(ChunkCoord(1, 2), chunk_size=8, halo=2)
    assert c.chunk_size == 8
    assert c.halo == 2
    assert c.cell_count == 64


# -- fields ----------------------------------------------------------------


def test_chunk_field_returns_field() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4, halo=1)
    f = c.field("altitude")
    assert isinstance(f, Field)
    assert f.dtype == np.dtype(np.float64)
    assert f.shape == (6, 6)
    assert f.interior.shape == (4, 4)


def test_chunk_field_unknown_name_raises() -> None:
    c = Chunk(ChunkCoord(0, 0))
    with pytest.raises(KeyError):
        c.field("nope")


def test_chunk_fields_always_present_from_schema() -> None:
    # No fields supplied: every schema field is present at its schema default.
    c = Chunk(ChunkCoord(0, 0), chunk_size=4, halo=1)
    assert set(c.field_names) == set(FIELD_NAMES)
    assert np.all(c.field("altitude").interior == 0.0)
    assert np.all(c.field("temperature").interior == 25.0)
    assert np.all(c.field("humidity").interior == 0.5)
    assert np.all(c.field("precipitation").interior == 0.0)
    assert np.all(c.field("biome_id").interior == 0)


def test_chunk_with_prefilled_fields() -> None:
    alt = np.full((4, 4), 7.0, dtype=np.float64)
    c = Chunk(ChunkCoord(0, 0), chunk_size=4, halo=1, fields={"altitude": alt})
    assert np.all(c.field("altitude").interior == 7.0)
    # Omitted fields fall back to their schema defaults.
    assert np.all(c.field("temperature").interior == 25.0)
    assert np.all(c.field("biome_id").interior == 0)


def test_chunk_prefill_wrong_shape_raises() -> None:
    bad = np.zeros((4, 3), dtype=np.float64)
    with pytest.raises(ValueError, match="shape"):
        Chunk(ChunkCoord(0, 0), chunk_size=4, halo=1, fields={"altitude": bad})


def test_chunk_prefill_unknown_name_raises() -> None:
    arr = np.zeros((4, 4), dtype=np.float64)
    with pytest.raises(KeyError):
        Chunk(ChunkCoord(0, 0), chunk_size=4, halo=1, fields={"not_a_field": arr})


# -- entity index ----------------------------------------------------------


def test_add_and_retrieve_entity() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e = _mock_entity()
    c.add_entity(e, 1, 2)
    assert e in c.entities_at(1, 2)
    assert c.inhabited_cells == 1


def test_empty_cell_returns_empty_frozenset() -> None:
    c = Chunk(ChunkCoord(0, 0))
    result = c.entities_at(0, 0)
    assert isinstance(result, frozenset)
    assert len(result) == 0


def test_remove_entity() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e = _mock_entity()
    c.add_entity(e, 1, 2)
    c.remove_entity(e, 1, 2)
    assert c.entities_at(1, 2) == frozenset()
    assert c.inhabited_cells == 0


def test_remove_entity_from_empty_cell_raises() -> None:
    c = Chunk(ChunkCoord(0, 0))
    with pytest.raises(KeyError):
        c.remove_entity(_mock_entity(), 0, 0)


def test_remove_nonexistent_entity_from_inhabited_cell_does_nothing() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e1 = _mock_entity()
    e2 = _mock_entity()
    c.add_entity(e1, 0, 0)
    # Removing e2 from (0,0) just discards silently; cell stays inhabited.
    c.remove_entity(e2, 0, 0)
    assert c.entities_at(0, 0) == frozenset({e1})


def test_move_entity() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e = _mock_entity()
    c.add_entity(e, 0, 0)
    c.move_entity(e, 0, 0, 2, 2)
    assert c.entities_at(0, 0) == frozenset()
    assert c.entities_at(2, 2) == frozenset({e})


def test_multiple_entities_same_cell() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e1, e2 = _mock_entity(), _mock_entity()
    c.add_entity(e1, 1, 1)
    c.add_entity(e2, 1, 1)
    assert c.entities_at(1, 1) == frozenset({e1, e2})
    assert c.inhabited_cells == 1
    c.remove_entity(e1, 1, 1)
    assert c.entities_at(1, 1) == frozenset({e2})


def test_clear_entity_removes_from_all_cells() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e = _mock_entity()
    c.add_entity(e, 0, 0)
    c.add_entity(e, 3, 3)
    c.clear_entity(e)
    assert c.entities_at(0, 0) == frozenset()
    assert c.entities_at(3, 3) == frozenset()
    assert c.inhabited_cells == 0


def test_entities_at_is_immutable_snapshot() -> None:
    c = Chunk(ChunkCoord(0, 0), chunk_size=4)
    e = _mock_entity()
    c.add_entity(e, 0, 0)
    snapshot = c.entities_at(0, 0)
    c.remove_entity(e, 0, 0)
    # Snapshot still contains e — it's a frozenset copy.
    assert e in snapshot
