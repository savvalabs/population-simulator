"""Tests for :mod:`population_engine.ecs.entity`."""

from __future__ import annotations

import pytest

from population_engine.ecs.entity import Entity, EntityAllocator
from population_engine.ecs.errors import InvalidEntityError


def test_allocate_yields_live_distinct_handles() -> None:
    a = EntityAllocator()
    e1 = a.allocate()
    e2 = a.allocate()
    assert a.is_alive(e1) and a.is_alive(e2)
    assert e1 != e2
    assert a.alive == 2
    assert a.capacity >= 2


def test_free_makes_handle_dead_and_recycles_slot() -> None:
    a = EntityAllocator()
    e1 = a.allocate()
    a.free(e1)
    assert not a.is_alive(e1)
    # The freed slot is recycled for the next allocation...
    e2 = a.allocate()
    assert a.is_alive(e2)
    assert e2.slot == e1.slot
    # ...with a bumped generation, so the old handle stays dead.
    assert e2.generation == e1.generation + 1
    assert e1 != e2
    assert not a.is_alive(e1)


def test_generation_counts_up_across_recycles() -> None:
    a = EntityAllocator()
    e = a.allocate()
    gens = [e.generation]
    for _ in range(3):
        a.free(e)
        e = a.allocate()
        gens.append(e.generation)
    assert gens[0] == 0 and gens[-1] == 3


def test_double_free_raises() -> None:
    a = EntityAllocator()
    e = a.allocate()
    a.free(e)
    with pytest.raises(InvalidEntityError):
        a.free(e)


def test_cannot_free_recycled_slot_via_stale_handle() -> None:
    a = EntityAllocator()
    e1 = a.allocate()
    a.free(e1)        # slot recycled on next alloc, gen bumped
    e2 = a.allocate()
    # The stale handle e1 now points at e2's slot but wrong generation.
    assert e1.slot == e2.slot
    with pytest.raises(InvalidEntityError):
        a.free(e1)


def test_is_alive_rejects_fully_unknown_handle() -> None:
    a = EntityAllocator()
    assert not a.is_alive(Entity(slot=999, generation=0))
    assert not a.is_alive(Entity(slot=-1, generation=0))


def test_alive_and_capacity_track_state() -> None:
    a = EntityAllocator()
    assert a.alive == 0
    e1, e2 = a.allocate(), a.allocate()
    assert a.alive == 2 and a.capacity == 2
    a.free(e1)
    assert a.alive == 1 and a.capacity == 2
