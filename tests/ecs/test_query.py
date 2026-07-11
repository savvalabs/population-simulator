"""Tests for :mod:`population_engine.ecs.query`."""

from __future__ import annotations

import pytest

from population_engine.ecs.query import Query
from population_engine.ecs.registry import Registry

from ._components import Health, Position, Tag, Velocity


def test_query_matches_supersets_in_multiple_archetypes() -> None:
    r = Registry()
    only_p = r.create_entity(Position(x=1))
    p_and_v = r.create_entity(Position(x=2), Velocity(vx=9))
    p_and_h = r.create_entity(Position(x=3), Health(hp=10))

    # Querying Position alone matches all three archetypes (they all have it).
    xs = sorted(pos.x for _, pos in r.query(Position))
    assert xs == [1, 2, 3]

    # Querying Position + Velocity matches only the {P,V} archetype.
    matches = {e: (pos, vel) for e, pos, vel in r.query(Position, Velocity)}
    assert set(matches) == {p_and_v}
    assert matches[p_and_v][1].vx == 9
    # The other two entities are correctly excluded.
    assert only_p not in matches and p_and_h not in matches


def test_query_yields_components_in_request_order() -> None:
    r = Registry()
    e = r.create_entity(Position(x=1), Velocity(vx=2))
    # Requesting Velocity before Position yields them in that order.
    row = next(r.query(Velocity, Position))
    entity, vel, pos = row
    assert entity is e
    assert isinstance(vel, Velocity) and isinstance(pos, Position)
    assert vel.vx == 2 and pos.x == 1


def test_query_deduplicates_requested_types() -> None:
    r = Registry()
    e = r.create_entity(Position(x=1))
    # Passing Position twice should still yield a single Position column.
    row = next(r.query(Position, Position))
    assert row[0] is e
    assert len(row) == 2  # entity + one Position


def test_query_returns_live_mutable_instances() -> None:
    r = Registry()
    e = r.create_entity(Position(x=0))
    for _, pos in r.query(Position):
        pos.x = 42
    assert r.get_component(e, Position).x == 42


def test_query_yields_creation_order_within_an_archetype() -> None:
    r = Registry()
    created = [r.create_entity(Position(x=i)) for i in range(5)]
    handles_in_query = [h for h, _ in r.query(Position)]
    assert handles_in_query == created


def test_query_no_matches_is_empty() -> None:
    r = Registry()
    r.create_entity(Position())
    assert list(r.query(Velocity)) == []


def test_query_requires_at_least_one_component() -> None:
    r = Registry()
    with pytest.raises(ValueError):
        r.query()
    with pytest.raises(ValueError):
        Query()


def test_query_survives_across_add_remove_transitions() -> None:
    r = Registry()
    e = r.create_entity(Position(x=1))
    # Before adding Velocity, a P+V query excludes it.
    assert list(r.query(Position, Velocity)) == []
    r.add_component(e, Velocity(vx=7))
    [(_, pos, vel)] = list(r.query(Position, Velocity))
    assert pos.x == 1 and vel.vx == 7
    r.remove_component(e, Velocity)
    assert list(r.query(Position, Velocity)) == []
