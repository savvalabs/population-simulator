"""Archetype storage.

An archetype groups entities that share exactly the same set of component
types. Within an archetype, each component type is a dense column (a Python
list) of component instances; rows are aligned across all columns and with the
:class:`~population_engine.ecs.entity.Entity` handle list. Dense columnar
storage gives linear, cache-friendly iteration to systems and is the structure
archetype ECS is built on. (Columns are backed by Python lists today; the
interface is shaped so a numeric column can be swapped in later without
changing systems.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .entity import Entity

__all__ = ["Archetype"]


@dataclass(slots=True)
class Archetype:
    """A group of entities sharing the same component set, stored columnarly."""

    signature: int
    types: tuple[type, ...]
    # Entity handles, aligned with every column in ``columns``.
    entities: list = field(default_factory=list)
    # component_type -> list[component_instance], row-aligned with ``entities``.
    columns: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entities)

    def add_row(self, entity: "Entity", components: dict) -> int:
        """Append an entity and its per-type components; return its row index.

        ``components`` must map exactly the archetype's component types to one
        instance each.
        """
        if components.keys() != set(self.types):
            raise ValueError(
                "components keys must exactly match the archetype's types; "
                f"expected {set(self.types)}, got {set(components)}"
            )
        for component_type in self.types:
            self.columns[component_type].append(components[component_type])
        self.entities.append(entity)
        return len(self.entities) - 1

    def remove_row(self, row: int):
        """Remove row ``row`` via swap-remove; return the moved entity or None.

        Returns the entity that was moved from the last row into ``row`` (so the
        caller can patch its stored row index), or ``None`` if ``row`` was the
        last row (nothing else moved). Keeps the columns dense.
        """
        last = len(self.entities) - 1
        if row < 0 or row > last:
            raise IndexError(f"row {row} out of range [0, {last}]")
        moved = self.entities[last] if row != last else None
        for column in self.columns.values():
            if row != last:
                column[row] = column[last]
            column.pop()
        if row != last:
            self.entities[row] = self.entities[last]
        self.entities.pop()
        return moved
