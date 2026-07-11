"""Tests for :mod:`population_engine.ecs.registry` (entities + components)."""

from __future__ import annotations

import pytest

from population_engine.ecs.errors import ComponentError, InvalidEntityError
from population_engine.ecs.registry import Registry

from ._components import Health, Position, Tag, Velocity


# -- component registration ------------------------------------------------

def test_register_component_assigns_stable_ids() -> None:
    r = Registry()
    id_p = r.register_component(Position)
    id_v = r.register_component(Velocity)
    assert id_p == 0 and id_v == 1
    # idempotent: same type -> same id
    assert r.register_component(Position) == id_p
    assert r.component_types == (Position, Velocity)


def test_register_rejects_non_component() -> None:
    r = Registry()
    with pytest.raises(ComponentError):
        r.register_component(int)  # not a Component subclass
    with pytest.raises(TypeError):
        r.register_component("not a class")  # type: ignore[arg-type]


# -- create / get / has ----------------------------------------------------

def test_create_entity_and_read_back_components() -> None:
    r = Registry()
    e = r.create_entity(Position(x=1, y=2), Health(hp=50))
    assert len(r) == 1 and r.entity_count == 1
    pos = r.get_component(e, Position)
    assert isinstance(pos, Position) and pos.x == 1 and pos.y == 2
    assert r.has_component(e, Health)
    assert r.get_component(e, Velocity) is None
    assert not r.has_component(e, Velocity)


def test_create_rejects_duplicate_and_non_component() -> None:
    r = Registry()
    with pytest.raises(ComponentError):
        r.create_entity(Position(), Position())  # duplicate component type
    with pytest.raises(ComponentError):
        r.create_entity(object())  # not a Component instance


def test_get_component_returns_same_live_instance() -> None:
    r = Registry()
    p = Position(x=3)
    e = r.create_entity(p)
    assert r.get_component(e, Position) is p
    # Mutating through the returned reference is visible to the registry.
    r.get_component(e, Position).x = 99
    assert r.get_component(e, Position).x == 99


# -- add / remove transitions ---------------------------------------------

def test_add_component_grows_archetype_and_preserves_others() -> None:
    r = Registry()
    p = Position(x=1, y=2)
    e = r.create_entity(p)
    starting_archetypes = r.archetype_count

    r.add_component(e, Velocity(vx=5, vy=6))
    assert r.archetype_count == starting_archetypes + 1
    # The position survived the transition (same object reference).
    assert r.get_component(e, Position) is p
    assert r.get_component(e, Velocity).vx == 5


def test_add_existing_component_raises() -> None:
    r = Registry()
    e = r.create_entity(Position())
    with pytest.raises(ComponentError):
        r.add_component(e, Position())


def test_remove_component_returns_instance_and_shrinks() -> None:
    r = Registry()
    p = Position()
    h = Health(hp=10)
    e = r.create_entity(p, h)
    starting_archetypes = r.archetype_count

    removed = r.remove_component(e, Health)
    assert removed is h
    assert r.archetype_count == starting_archetypes + 1
    assert not r.has_component(e, Health)
    # The position survived the transition (same object reference).
    assert r.get_component(e, Position) is p


def test_remove_missing_component_raises() -> None:
    r = Registry()
    e = r.create_entity(Position())
    with pytest.raises(ComponentError):
        r.remove_component(e, Health)


def test_add_then_remove_round_trips_to_position_only() -> None:
    r = Registry()
    e = r.create_entity(Position())
    # Archetypes are retained when emptied (they cache edge transitions and are
    # reused on re-creation), so the {P,V} archetype sticks around but empties.
    r.add_component(e, Velocity())
    assert len(list(r.query(Position, Velocity))) == 1
    r.remove_component(e, Velocity)
    # Back to {Position}: the entity holds only Position, and the {P,V} row is gone.
    assert r.has_component(e, Position)
    assert not r.has_component(e, Velocity)
    assert len(list(r.query(Position, Velocity))) == 0
    assert len(list(r.query(Position))) == 1


# -- destroy ---------------------------------------------------------------

def test_destroy_releases_entity_and_invalidates_handle() -> None:
    r = Registry()
    e = r.create_entity(Position(), Health())
    r.destroy_entity(e)
    assert len(r) == 0
    for op in (
        lambda: r.get_component(e, Position),
        lambda: r.has_component(e, Position),
        lambda: r.add_component(e, Velocity()),
        lambda: r.remove_component(e, Position),
        lambda: r.destroy_entity(e),
    ):
        with pytest.raises(InvalidEntityError):
            op()


def test_destroy_patches_moved_entity_row_indices() -> None:
    # Three entities in one archetype; destroying the first swaps the last into
    # row 0. The moved entity must remain queryable and intact.
    r = Registry()
    a = r.create_entity(Position(x=1))
    b = r.create_entity(Position(x=2))
    c = r.create_entity(Position(x=3))
    r.destroy_entity(a)
    assert len(r) == 2
    survivors = {p.x: p for _, p in r.query(Position)}
    # b and c survive; their data must be intact.
    assert {2, 3} <= set(survivors)
    # Re-querying after a second destroy still works (rows stay dense).
    r.destroy_entity(b)
    assert len(r) == 1
    [(_, only)] = list(r.query(Position))
    assert only.x == 3


# -- alive entities ---------------------------------------------------------

def test_alive_entities_lists_live_handles() -> None:
    r = Registry()
    e1 = r.create_entity(Position())
    e2 = r.create_entity(Position(), Health())
    living = set(r.alive_entities())
    assert {e1, e2} == living
    r.destroy_entity(e1)
    assert set(r.alive_entities()) == {e2}
