"""Component types.

Components are plain data containers (typically ``@dataclass``) describing one
slice of an entity's state. They carry no behaviour: systems read and mutate
component instances in place. Component *types* are registered with the ECS
registry, which assigns each a stable integer id used to build fast bitmask
signatures for archetype lookup.

Inheriting from :class:`Component` is required so the registry can distinguish
intended component types from arbitrary classes. Components should be mutable
dataclasses so systems can mutate them in place::

    from dataclasses import dataclass
    from population_engine.ecs import Component

    @dataclass
    class Position(Component):
        x: int = 0
        y: int = 0
"""

from __future__ import annotations

__all__ = ["Component"]


class Component:
    """Marker base class for ECS components.

    Subclass it (typically with ``@dataclass``) to define a component type. The
    class itself is the component's identity; instances carry the per-entity
    data and are mutated in place by systems. The class is intentionally
    behaviour-free: all logic lives in systems, never in components.
    """
