"""Tests for :mod:`population_engine.world.coords`."""

from __future__ import annotations

import pytest

from population_engine.world.coords import CellCoord, ChunkCoord

CHUNK = 32


# -- CellCoord ------------------------------------------------------------


def test_cell_coord_creation_and_equality() -> None:
    a = CellCoord(x=5, y=10)
    b = CellCoord(x=5, y=10)
    c = CellCoord(x=6, y=10)
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_cell_coord_is_frozen() -> None:
    c = CellCoord(0, 0)
    with pytest.raises(Exception):
        c.x = 1  # type: ignore[misc]


def test_cell_coord_to_chunk_origin() -> None:
    assert CellCoord(0, 0).to_chunk(CHUNK) == ChunkCoord(0, 0)
    assert CellCoord(31, 31).to_chunk(CHUNK) == ChunkCoord(0, 0)


def test_cell_coord_to_chunk_boundary() -> None:
    assert CellCoord(32, 0).to_chunk(CHUNK) == ChunkCoord(1, 0)
    assert CellCoord(0, 32).to_chunk(CHUNK) == ChunkCoord(0, 1)
    assert CellCoord(32, 32).to_chunk(CHUNK) == ChunkCoord(1, 1)


def test_cell_coord_to_chunk_negative() -> None:
    assert CellCoord(-1, -1).to_chunk(CHUNK) == ChunkCoord(-1, -1)
    assert CellCoord(-32, 0).to_chunk(CHUNK) == ChunkCoord(-1, 0)


def test_local_offset_origin() -> None:
    assert CellCoord(0, 0).local_offset(CHUNK) == (0, 0)


def test_local_offset_near_boundary() -> None:
    assert CellCoord(31, 63).local_offset(CHUNK) == (31, 31)
    assert CellCoord(32, 0).local_offset(CHUNK) == (0, 0)
    assert CellCoord(-1, -1).local_offset(CHUNK) == (31, 31)


# -- ChunkCoord -----------------------------------------------------------


def test_chunk_coord_creation_and_equality() -> None:
    a = ChunkCoord(ix=2, iy=3)
    b = ChunkCoord(ix=2, iy=3)
    c = ChunkCoord(ix=3, iy=3)
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_chunk_coord_is_frozen() -> None:
    c = ChunkCoord(0, 0)
    with pytest.raises(Exception):
        c.ix = 1  # type: ignore[misc]


def test_cell_origin_zero() -> None:
    assert ChunkCoord(0, 0).cell_origin(CHUNK) == CellCoord(0, 0)


def test_cell_origin_offset() -> None:
    assert ChunkCoord(1, 0).cell_origin(CHUNK) == CellCoord(32, 0)
    assert ChunkCoord(0, 1).cell_origin(CHUNK) == CellCoord(0, 32)
    assert ChunkCoord(1, 2).cell_origin(CHUNK) == CellCoord(32, 64)


def test_cell_range() -> None:
    mn, mx = ChunkCoord(0, 0).cell_range(CHUNK)
    assert mn == CellCoord(0, 0)
    assert mx == CellCoord(32, 32)  # exclusive


def test_cell_range_offset_chunk() -> None:
    mn, mx = ChunkCoord(2, 3).cell_range(CHUNK)
    assert mn == CellCoord(64, 96)
    assert mx == CellCoord(96, 128)


# -- round-trip -----------------------------------------------------------


def test_cell_to_chunk_and_back_round_trips() -> None:
    cell = CellCoord(x=70, y=130)
    chunk = cell.to_chunk(CHUNK)
    origin = chunk.cell_origin(CHUNK)
    lx, ly = cell.local_offset(CHUNK)
    assert origin.x + lx == 70
    assert origin.y + ly == 130


def test_ordering_semantics() -> None:
    # frozen dataclasses with order=True support comparison
    cells = [CellCoord(2, 3), CellCoord(0, 5), CellCoord(1, 1)]
    assert sorted(cells) == [CellCoord(0, 5), CellCoord(1, 1), CellCoord(2, 3)]

    chunks = [ChunkCoord(1, 0), ChunkCoord(0, 0), ChunkCoord(0, 2)]
    assert sorted(chunks) == [ChunkCoord(0, 0), ChunkCoord(0, 2), ChunkCoord(1, 0)]