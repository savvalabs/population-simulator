"""Queries.

A :class:`Query` selects all entities whose component set is a superset of the
requested types, and yields, for each match, the entity handle plus a tuple of
its requested component instances (in request order). Matching walks archetypes
and tests bitmask signatures, so a query is cheap to create and linear in the
matching rows it visits.

Queries are created reusably and bound to a registry at iteration time::

    q = Query(Position, Velocity)
    for entity, position, velocity in q.iter(registry):
        ...

or via the convenience ``registry.query(Position, Velocity)``.

Mutating the registry (adding/removing components or destroying entities) while
a query iterator is live is unsafe: collect the results first, then mutate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from .registry import Registry

__all__ = ["Query"]


class Query:
    """A reusable selection of entities by component set."""

    __slots__ = ("types",)

    def __init__(self, *types: type) -> None:
        if not types:
            raise ValueError("a Query requires at least one component type")
        # Drop duplicates while preserving the caller's order, so the yielded
        # tuple matches the requested order one-to-one.
        self.types: tuple[type, ...] = tuple(dict.fromkeys(types))

    def iter(self, registry: "Registry") -> Iterator[tuple]:
        """Yield ``(entity, *component_instances)`` for every matching entity.

        Component instances are yielded in the order the component types were
        passed to the constructor. The same live instances stored by the
        registry are returned (by reference), so mutating them visibly updates
        the entity's state.
        """
        types = self.types
        ids = [registry.register_component(t) for t in types]
        mask = 0
        for cid in ids:
            mask |= 1 << cid
        for arch in registry._iter_archetypes():  # noqa: SLF001 - registry friendship
            if (arch.signature & mask) != mask:
                continue
            columns = [arch.columns[t] for t in types]
            entities = arch.entities
            row_count = len(entities)
            for row in range(row_count):
                yield (entities[row],) + tuple(
                    columns[col][row] for col in range(len(columns))
                )
