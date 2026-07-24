"""Tests for :mod:`population_engine.world.world`."""

from __future__ import annotations

import numpy as np
import pytest

from population_engine.ecs.entity import Entity
from population_engine.world.biome import Biome
from population_engine.world.chunk import DEFAULT_CHUNK_SIZE
from population_engine.world.coords import CellCoord, ChunkCoord
from population_engine.world.field import DEFAULT_HALO
from population_engine.world.world import World


def _entity() -> Entity:
    from population_engine.ecs.entity import EntityAllocator

    return EntityAllocator().allocate()


def _world(**kwargs) -> World:
    """Create a bounded World with fast, deterministic test defaults."""
    defaults: dict = {
        "seed": 42,
        "chunk_size": 8,
        "width_chunks": 2,
        "height_chunks": 2,
    }
    defaults.update(kwargs)
    return World(**defaults)


def _tier_biomes() -> list[Biome]:
    """Three altitude/temperature tiers (default humidity range)."""
    return [
        Biome("low", min_altitude=0, max_altitude=1000, min_temperature=20, max_temperature=30),
        Biome("mid", min_altitude=1000, max_altitude=3000, min_temperature=10, max_temperature=20),
        Biome("high", min_altitude=3000, max_altitude=6000, min_temperature=0, max_temperature=10),
    ]


# -- construction ----------------------------------------------------------


def test_world_defaults() -> None:
    w = World()
    assert w.chunk_size == DEFAULT_CHUNK_SIZE
    assert w.halo == DEFAULT_HALO
    assert w.width_chunks == 8
    assert w.height_chunks == 8
    assert w.loaded_chunks == 64  # all generated up front
    assert w.biomes == ()


def test_world_custom_dims() -> None:
    w = World(seed=1, width_chunks=3, height_chunks=2, chunk_size=4, halo=2)
    assert w.width_chunks == 3
    assert w.height_chunks == 2
    assert w.chunk_size == 4
    assert w.halo == 2
    assert w.loaded_chunks == 6


def test_world_with_biomes() -> None:
    b = [Biome("a"), Biome("b")]
    w = World(biomes=b)
    assert w.biomes == (b[0], b[1])


def test_invalid_dims_raise() -> None:
    with pytest.raises(ValueError):
        World(width_chunks=0)
    with pytest.raises(ValueError):
        World(height_chunks=0)
    with pytest.raises(ValueError):
        World(chunk_size=0)
    with pytest.raises(ValueError):
        World(halo=0)  # halo >= 1 required


def test_chunks_pre_built_up_front() -> None:
    w = _world()
    assert w.loaded_chunks == 4  # 2x2, no lazy generation
    # Querying the highest-index chunk does not grow the count.
    before = w.loaded_chunks
    w.chunk(ChunkCoord(1, 1))
    assert w.loaded_chunks == before


# -- chunk management -------------------------------------------------------


def test_has_chunk_pure_bounds() -> None:
    w = _world()
    assert w.has_chunk(ChunkCoord(0, 0))
    assert w.has_chunk(ChunkCoord(1, 1))
    assert not w.has_chunk(ChunkCoord(2, 0))
    assert not w.has_chunk(ChunkCoord(0, -1))


def test_chunk_returns_same_instance() -> None:
    w = _world()
    a = w.chunk(ChunkCoord(0, 0))
    b = w.chunk(ChunkCoord(0, 0))
    assert a is b


def test_chunk_oob_raises() -> None:
    w = _world()
    with pytest.raises(IndexError):
        w.chunk(ChunkCoord(5, 5))
    with pytest.raises(IndexError):
        w.chunk(ChunkCoord(-1, 0))


# -- determinism ------------------------------------------------------------


def test_same_seed_equal_interiors() -> None:
    w1 = _world(seed=42)
    w2 = _world(seed=42)
    for iy in range(2):
        for ix in range(2):
            c1 = w1.chunk(ChunkCoord(ix, iy))
            c2 = w2.chunk(ChunkCoord(ix, iy))
            for name in ("altitude", "temperature", "humidity", "biome_id"):
                assert np.array_equal(
                    c1.field(name).interior,
                    c2.field(name).interior,
                ), f"field {name!r} differs at chunk ({ix},{iy})"


def test_different_seeds_produce_different_altitude() -> None:
    w1 = _world(seed=42)
    w2 = _world(seed=99)
    assert not np.array_equal(
        w1.chunk(ChunkCoord(0, 0)).field("altitude").interior,
        w2.chunk(ChunkCoord(0, 0)).field("altitude").interior,
    )


# -- field access -----------------------------------------------------------


def test_value_returns_scalar() -> None:
    w = _world()
    v = w.value("altitude", CellCoord(0, 0))
    assert isinstance(v, np.floating)
    assert v > 0  # mountain core near the world origin
    b = w.value("biome_id", CellCoord(0, 0))
    assert isinstance(b, np.integer)
    assert b >= 0


def test_value_unknown_name_raises() -> None:
    w = _world()
    with pytest.raises(KeyError):
        w.value("nope", CellCoord(0, 0))


def test_value_out_of_bounds_raises() -> None:
    w = _world()
    with pytest.raises(IndexError):
        w.value("altitude", CellCoord(100, 100))


def test_value_equals_chunk_interior() -> None:
    w = _world()
    coord = CellCoord(3, 4)
    ck = coord.to_chunk(w.chunk_size)
    lx, ly = coord.local_offset(w.chunk_size)
    assert w.value("altitude", coord) == w.chunk(ck).field("altitude").interior[ly, lx]


def test_value_reads_interior_write() -> None:
    w = _world()
    coord = CellCoord(3, 4)
    ck = coord.to_chunk(w.chunk_size)
    lx, ly = coord.local_offset(w.chunk_size)
    w.chunk(ck).field("altitude").interior[ly, lx] = 8888.0
    assert w.value("altitude", coord) == 8888.0


# -- classification ---------------------------------------------------------


def test_classify_scalar_first_match() -> None:
    # Two overlapping biomes; the earlier one wins.
    biomes = [
        Biome("low", min_altitude=0, max_altitude=1000),
        Biome("broad", min_altitude=0, max_altitude=5000),
    ]
    w = _world(seed=1, biomes=biomes)
    # (500, 25, 0.5) matches both 'low' and 'broad' → first match = index 0.
    assert w.classify(500, 25, 0.5) == 0


def test_classify_scalar_tiers() -> None:
    w = _world(seed=1, biomes=_tier_biomes())
    assert w.classify(500, 25, 0.5) == 0
    assert w.classify(1500, 15, 0.5) == 1
    assert w.classify(3500, 5, 0.5) == 2


def test_classify_scalar_no_match_returns_zero() -> None:
    biomes = [
        Biome("cold", min_temperature=-50, max_temperature=0),
        Biome("hot", min_temperature=40, max_temperature=100),
    ]
    w = _world(seed=1, biomes=biomes)
    # temperature 25 matches neither → default 0 (unclassified).
    assert w.classify(100, 25, 0.5) == 0


def test_classify_chunk_matches_scalar_per_cell() -> None:
    w = _world(seed=1, biomes=_tier_biomes())
    c = w.chunk(ChunkCoord(0, 0))
    ids = w.classify_chunk(c)
    assert ids.dtype == np.dtype(np.int64)
    assert ids.shape == (w.chunk_size, w.chunk_size)
    alt = c.field("altitude").interior
    temp = c.field("temperature").interior
    hum = c.field("humidity").interior
    for ly in range(w.chunk_size):
        for lx in range(w.chunk_size):
            assert ids[ly, lx] == w.classify(alt[ly, lx], temp[ly, lx], hum[ly, lx]), (
                f"({ly},{lx})"
            )


def test_generated_biome_id_equals_classify_chunk() -> None:
    w = _world(seed=1, biomes=_tier_biomes())
    coords = [ChunkCoord(0, 0), ChunkCoord(1, 0), ChunkCoord(0, 1), ChunkCoord(1, 1)]
    for ck in coords:
        c = w.chunk(ck)
        assert np.array_equal(c.field("biome_id").interior, w.classify_chunk(c))


# -- halo (reflective boundary) --------------------------------------------


def test_halos_populated_after_construction() -> None:
    # After construction the top halo of a world-edge chunk mirrors its own top edge
    # (reflective), which is nonzero near the mountain core — not the schema default 0.0.
    w = _world()
    f = w.chunk(ChunkCoord(0, 0)).field("altitude")
    h, S = w.halo, w.chunk_size
    assert np.array_equal(f.data[0, h : h + S], f.interior[0, :])
    assert f.data[0, h : h + S].sum() != 0.0


def test_reflective_boundary_all_four_sides() -> None:
    w = _world()
    h, S = w.halo, w.chunk_size
    # top world edge (chunk row 0)
    f = w.chunk(ChunkCoord(0, 0)).field("altitude")
    assert np.array_equal(f.data[0, h : h + S], f.interior[0, :])
    # bottom world edge (chunk row 1)
    f = w.chunk(ChunkCoord(0, 1)).field("altitude")
    assert np.array_equal(f.data[-1, h : h + S], f.interior[-1, :])
    # left world edge (chunk col 0)
    f = w.chunk(ChunkCoord(0, 0)).field("altitude")
    assert np.array_equal(f.data[h : h + S, 0], f.interior[:, 0])
    # right world edge (chunk col 1)
    f = w.chunk(ChunkCoord(1, 0)).field("altitude")
    assert np.array_equal(f.data[h : h + S, -1], f.interior[:, -1])


def test_neighbour_mirror_across_seam() -> None:
    w = _world()
    h, S = w.halo, w.chunk_size
    left = w.chunk(ChunkCoord(0, 0)).field("altitude")
    right_chunk = w.chunk(ChunkCoord(1, 0)).field("altitude")
    # chunk(0,0) right halo = chunk(1,0) left interior column.
    assert np.array_equal(left.data[h : h + S, -1], right_chunk.interior[:, 0])

    top = w.chunk(ChunkCoord(0, 0)).field("altitude")
    bottom_chunk = w.chunk(ChunkCoord(0, 1)).field("altitude")
    # chunk(0,0) bottom halo = chunk(0,1) top interior row.
    assert np.array_equal(top.data[-1, h : h + S], bottom_chunk.interior[0, :])


def test_diagonal_neighbour_corner() -> None:
    w = _world()
    f = w.chunk(ChunkCoord(0, 0)).field("altitude")
    diag = w.chunk(ChunkCoord(1, 1)).field("altitude")
    # bottom-right halo corner of chunk(0,0) = top-left interior of chunk(1,1).
    assert f.data[-1, -1] == diag.interior[0, 0]


def test_world_corner_reflective() -> None:
    w = _world()
    f = w.chunk(ChunkCoord(0, 0)).field("altitude")
    # top-left world corner: halo corner mirrors own interior corner.
    assert f.data[0, 0] == f.interior[0, 0]
    f11 = w.chunk(ChunkCoord(1, 1)).field("altitude")
    # bottom-right world corner of the grid.
    assert f11.data[-1, -1] == f11.interior[-1, -1]


def test_refresh_halos_propagates_write() -> None:
    w = _world()
    h = w.halo
    sentinel = 12345.6
    # Write a sentinel on chunk(1,0)'s left edge interior (the seam-facing column).
    w.chunk(ChunkCoord(1, 0)).field("altitude").interior[3, 0] = sentinel
    w.refresh_halos()
    # It must surface in chunk(0,0)'s right halo at the same row.
    c0 = w.chunk(ChunkCoord(0, 0)).field("altitude")
    assert c0.data[h + 3, -1] == sentinel


# -- spatial entity queries (bounded) --------------------------------------


def test_add_and_retrieve_entity() -> None:
    w = _world()
    e = _entity()
    coord = CellCoord(0, 0)
    w.add_entity(e, coord)
    assert e in w.entities_at(coord)


def test_entities_at_empty_cell_returns_empty() -> None:
    w = _world()
    result = w.entities_at(CellCoord(5, 5))
    assert isinstance(result, frozenset)
    assert len(result) == 0


def test_entities_at_out_of_bounds_returns_empty() -> None:
    w = _world()
    assert w.entities_at(CellCoord(100, 100)) == frozenset()


def test_remove_entity() -> None:
    w = _world()
    e = _entity()
    coord = CellCoord(0, 0)
    w.add_entity(e, coord)
    w.remove_entity(e, coord)
    assert w.entities_at(coord) == frozenset()


def test_move_entity_within_same_chunk() -> None:
    w = _world()
    e = _entity()
    w.add_entity(e, CellCoord(0, 0))
    w.move_entity(e, CellCoord(0, 0), CellCoord(5, 5))
    assert w.entities_at(CellCoord(0, 0)) == frozenset()
    assert w.entities_at(CellCoord(5, 5)) == frozenset({e})


def test_move_entity_across_chunks() -> None:
    w = _world()
    before = w.loaded_chunks
    e = _entity()
    w.add_entity(e, CellCoord(0, 0))
    w.move_entity(e, CellCoord(0, 0), CellCoord(10, 10))
    assert w.entities_at(CellCoord(0, 0)) == frozenset()
    assert w.entities_at(CellCoord(10, 10)) == frozenset({e})
    assert w.loaded_chunks == before  # bounded: no new chunks materialise


def test_clear_entity_across_chunks() -> None:
    w = _world()
    e = _entity()
    w.add_entity(e, CellCoord(0, 0))
    w.add_entity(e, CellCoord(10, 10))
    w.clear_entity(e)
    assert w.entities_at(CellCoord(0, 0)) == frozenset()
    assert w.entities_at(CellCoord(10, 10)) == frozenset()


def test_multiple_entities_same_cell() -> None:
    w = _world()
    e1, e2 = _entity(), _entity()
    coord = CellCoord(0, 0)
    w.add_entity(e1, coord)
    w.add_entity(e2, coord)
    assert w.entities_at(coord) == frozenset({e1, e2})
    w.remove_entity(e1, coord)
    assert w.entities_at(coord) == frozenset({e2})


def test_add_entity_out_of_bounds_raises() -> None:
    w = _world()
    with pytest.raises(IndexError):
        w.add_entity(_entity(), CellCoord(100, 100))


def test_remove_entity_out_of_bounds_raises() -> None:
    w = _world()
    with pytest.raises(IndexError):
        w.remove_entity(_entity(), CellCoord(100, 100))


def test_move_entity_out_of_bounds_raises() -> None:
    w = _world()
    e = _entity()
    w.add_entity(e, CellCoord(0, 0))
    with pytest.raises(IndexError):
        w.move_entity(e, CellCoord(0, 0), CellCoord(100, 100))
