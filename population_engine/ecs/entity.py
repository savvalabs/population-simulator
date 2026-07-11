"""Entity handles and allocation.

Entities are opaque, cheaply-copyable identifiers. A handle is a ``(slot,
generation)`` pair: ``slot`` indexes per-entity storage in the ECS registry;
``generation`` invalidates handles that referred to an entity which has since
been destroyed (and whose slot may have been recycled for a new entity).

The :class:`EntityAllocator` owns the slot/generation table and a free-list and
is used by the ECS :class:`~population_engine.ecs.registry.Registry` to mint
and retire handles. Handles compare equal only when both slot and generation
match, so a stale handle never aliases a recycled entity.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidEntityError

__all__ = ["Entity", "EntityAllocator"]


@dataclass(frozen=True, slots=True)
class Entity:
    """An opaque entity identifier."""

    slot: int
    generation: int


class EntityAllocator:
    """Assigns and recycles entity slots with generation-tagged handles."""

    __slots__ = ("_alive", "_generation", "_free")

    def __init__(self) -> None:
        self._alive: list[bool] = []
        self._generation: list[int] = []
        # LIFO of freed slots; reused so dead handles (with a stale generation)
        # never collide with the freshly-allocated entities that take their slot.
        self._free: list[int] = []

    def allocate(self) -> Entity:
        """Mint a new live entity handle."""
        if self._free:
            slot = self._free.pop()
        else:
            slot = len(self._alive)
            self._alive.append(False)
            self._generation.append(0)
        self._alive[slot] = True
        return Entity(slot, self._generation[slot])

    def free(self, entity: Entity) -> None:
        """Retire a live handle and recycle its slot for future allocation."""
        if not self.is_alive(entity):
            raise InvalidEntityError(f"cannot free a dead or unknown entity {entity!r}")
        self._alive[entity.slot] = False
        # Bump the generation so every outstanding handle to this slot is stale.
        self._generation[entity.slot] += 1
        self._free.append(entity.slot)

    def is_alive(self, entity: Entity) -> bool:
        """True iff ``entity`` refers to a currently-live entity."""
        slot = entity.slot
        if not 0 <= slot < len(self._alive):
            return False
        return self._alive[slot] and self._generation[slot] == entity.generation

    @property
    def capacity(self) -> int:
        """Total slots ever allocated (live and recycled)."""
        return len(self._alive)

    @property
    def alive(self) -> int:
        """Number of currently-live entities."""
        return sum(1 for a in self._alive if a)
