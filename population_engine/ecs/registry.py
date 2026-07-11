"""The ECS registry: entities, components, and archetype storage.

The registry is the central ECS store. It mints entity handles, registers
component types, stores component instances in archetype columns, and answers
queries. Adding or removing a component moves an entity between archetypes
(the classic archetype *edge transition*) while preserving its remaining
component data: the surviving component instances are the same objects, just
re-homed into the new archetype's columns.
"""

from __future__ import annotations

from typing import Iterator

from .archetype import Archetype
from .component import Component
from .entity import Entity, EntityAllocator
from .errors import ComponentError, InvalidEntityError
from .query import Query

__all__ = ["Registry"]


class Registry:
    """Central ECS store of entities and their components."""

    __slots__ = (
        "_allocator",
        "_comp_ids",
        "_id_to_type",
        "_archetypes",
        "_loc_archetype",
        "_loc_row",
        "_alive_count",
    )

    def __init__(self) -> None:
        self._allocator = EntityAllocator()
        self._comp_ids: dict[type, int] = {}
        self._id_to_type: list[type] = []
        # signature -> Archetype
        self._archetypes: dict[int, Archetype] = {}
        # per-slot location, indexed by entity.slot (only valid while alive):
        self._loc_archetype: list = []  # slot -> Archetype | None
        self._loc_row: list = []        # slot -> int | None
        self._alive_count = 0

    # -- component types ------------------------------------------------

    def register_component(self, component_type: type) -> int:
        """Assign (or return) the stable integer id for a component type."""
        if not isinstance(component_type, type):
            raise TypeError(f"component type must be a class, got {component_type!r}")
        if not issubclass(component_type, Component):
            raise ComponentError(
                f"{component_type!r} must subclass population_engine.ecs.Component"
            )
        existing = self._comp_ids.get(component_type)
        if existing is not None:
            return existing
        cid = len(self._id_to_type)
        self._id_to_type.append(component_type)
        self._comp_ids[component_type] = cid
        return cid

    @property
    def component_types(self) -> tuple[type, ...]:
        """All registered component types in id order."""
        return tuple(self._id_to_type)

    @property
    def archetype_count(self) -> int:
        """Number of distinct archetypes (component-set combinations) in use."""
        return len(self._archetypes)

    @property
    def entity_count(self) -> int:
        """Number of currently-live entities."""
        return self._alive_count

    def component_id(self, component_type: type) -> int:
        """The stable id for a registered component type (registers if new)."""
        return self.register_component(component_type)

    # -- entity lifecycle ----------------------------------------------

    def _ensure_slot(self, slot: int) -> None:
        while len(self._loc_archetype) <= slot:
            self._loc_archetype.append(None)
            self._loc_row.append(None)

    def _require_alive(self, entity: Entity) -> None:
        if not self._allocator.is_alive(entity):
            raise InvalidEntityError(f"entity {entity!r} is not alive")

    def create_entity(self, *components: Component) -> Entity:
        """Create a new entity holding exactly the given component instances."""
        seen: set[type] = set()
        for component in components:
            if not isinstance(component, Component):
                raise ComponentError(f"expected Component instances, got {component!r}")
            ct = type(component)
            if ct in seen:
                raise ComponentError(f"duplicate component {ct!r} for new entity")
            seen.add(ct)
        signature = 0
        for t in seen:
            signature |= 1 << self.register_component(t)
        arch = self._get_archetype(signature, tuple(seen))
        entity = self._allocator.allocate()
        self._ensure_slot(entity.slot)
        row = arch.add_row(entity, {type(c): c for c in components})
        self._loc_archetype[entity.slot] = arch
        self._loc_row[entity.slot] = row
        self._alive_count += 1
        return entity

    def destroy_entity(self, entity: Entity) -> None:
        """Destroy an entity, recycling its slot and dropping its components."""
        self._require_alive(entity)
        arch = self._loc_archetype[entity.slot]
        row = self._loc_row[entity.slot]
        moved = arch.remove_row(row)
        if moved is not None:
            self._loc_row[moved.slot] = row
        self._loc_archetype[entity.slot] = None
        self._loc_row[entity.slot] = None
        self._allocator.free(entity)
        self._alive_count -= 1

    # -- component operations ------------------------------------------

    def add_component(self, entity: Entity, component: Component) -> None:
        """Attach a new component, moving the entity into the extended archetype."""
        self._require_alive(entity)
        if not isinstance(component, Component):
            raise ComponentError(f"expected a Component instance, got {component!r}")
        ct = type(component)
        arch = self._loc_archetype[entity.slot]
        row = self._loc_row[entity.slot]
        columns = arch.columns
        if ct in columns:
            raise ComponentError(f"entity {entity!r} already has a {ct!r} component")
        # Snapshot surviving instances (by reference) before the row moves.
        existing = {t: columns[t][row] for t in arch.types}
        existing[ct] = component
        cid = self.register_component(ct)
        new_arch = self._get_archetype(arch.signature | (1 << cid), tuple(existing.keys()))
        moved = arch.remove_row(row)
        if moved is not None:
            self._loc_row[moved.slot] = row
        self._loc_row[entity.slot] = new_arch.add_row(entity, existing)
        self._loc_archetype[entity.slot] = new_arch

    def remove_component(self, entity: Entity, component_type: type) -> Component:
        """Detach a component, moving the entity into the reduced archetype.

        Returns the detached component instance (the same object the entity
        held). Raises :class:`ComponentError` if the entity has no such
        component.
        """
        self._require_alive(entity)
        if not isinstance(component_type, type):
            raise TypeError(f"component_type must be a class, got {component_type!r}")
        arch = self._loc_archetype[entity.slot]
        row = self._loc_row[entity.slot]
        columns = arch.columns
        if component_type not in columns:
            raise ComponentError(
                f"entity {entity!r} has no {component_type!r} component to remove"
            )
        removed = columns[component_type][row]
        existing = {t: columns[t][row] for t in arch.types if t is not component_type}
        cid = self.register_component(component_type)
        new_arch = self._get_archetype(arch.signature & ~(1 << cid), tuple(existing.keys()))
        moved = arch.remove_row(row)
        if moved is not None:
            self._loc_row[moved.slot] = row
        self._loc_row[entity.slot] = new_arch.add_row(entity, existing)
        self._loc_archetype[entity.slot] = new_arch
        return removed

    def get_component(self, entity: Entity, component_type: type) -> Component | None:
        """Return the entity's component instance, or ``None`` if it has none."""
        self._require_alive(entity)
        arch = self._loc_archetype[entity.slot]
        column = arch.columns.get(component_type)
        if column is None:
            return None
        return column[self._loc_row[entity.slot]]

    def has_component(self, entity: Entity, component_type: type) -> bool:
        """True iff the entity currently holds ``component_type``."""
        self._require_alive(entity)
        return component_type in self._loc_archetype[entity.slot].columns

    # -- archetype internals ------------------------------------------

    def _get_archetype(self, signature: int, types: tuple[type, ...]) -> Archetype:
        arch = self._archetypes.get(signature)
        if arch is not None:
            return arch
        # A deterministic component-type order (by id) for the stored tuple.
        ordered = tuple(sorted(types, key=self._comp_ids.__getitem__))
        arch = Archetype(signature, ordered, [], {t: [] for t in ordered})
        self._archetypes[signature] = arch
        return arch

    def _iter_archetypes(self) -> Iterator[Archetype]:
        return iter(self._archetypes.values())

    # -- queries & inspection -----------------------------------------

    def query(self, *types: type) -> Iterator[tuple]:
        """Return an iterator over matches for ``Query(*types)``.

        Shorthand for ``Query(*types).iter(self)``.
        """
        return Query(*types).iter(self)

    def alive_entities(self) -> Iterator[Entity]:
        """Yield every currently-live entity handle (in archetype order)."""
        for arch in self._archetypes.values():
            for entity in arch.entities:
                yield entity

    def __len__(self) -> int:
        return self._alive_count
