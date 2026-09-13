"""ExposureSystem: the decoupling hinge (CORE_DESIGN §3.1).

The ONLY entity-facing system allowed to read the World. Once per tick it:
1. iterates every entity carrying a :class:`Position`,
2. resolves the entity's exact cell,
3. snapshots that cell's climate Fields into a :class:`CellExposure`
   component (creating it if absent).

Downstream entity systems (``EnvironmentPressureSystem``, foraging, census,
...) read ``CellExposure`` and never touch ``world.value`` — keeping the
entity pipeline world-free and unit-testable with synthetic components.
"""

from __future__ import annotations

from ..ecs.components import CellExposure, Position
from ..ecs.scheduler import System, SystemContext
from ..world.coords import CellCoord

__all__ = ["ExposureSystem"]

_SNAPSHOT_FIELDS: tuple[str, ...] = ("temperature", "humidity", "precipitation")


class ExposureSystem(System):
    """Snapshot the local cell climate of every positioned entity."""

    name = "exposure"
    reads: tuple = (Position,)
    writes: tuple = (CellExposure,)
    # Reads the climate Fields written by ClimateSystem: a non-component
    # dependency the scheduler cannot infer, so it must be declared.
    after: tuple = ("climate",)

    def update(self, ctx: SystemContext) -> None:
        world = ctx.world
        if world is None:
            return
        registry = ctx.registry
        # Pass 1: entities lacking CellExposure get one attached AFTER the
        # query is exhausted (never mutate archetypes mid-iteration, ADR-004
        # interim pattern as in DeathSystem). Spawn should attach it; this is
        # a defensive backfill for hand-built entities.
        missing = [
            entity
            for entity, _pos in registry.query(Position)
            if not registry.has_component(entity, CellExposure)
        ]
        for entity in missing:
            registry.add_component(entity, CellExposure())
        # Pass 2: snapshot the cell climate into every positioned entity.
        query = registry.query(Position, CellExposure)
        for _entity, position, exposure in query:
            cell = CellCoord(position.x, position.y)
            exposure.temperature = float(world.value("temperature", cell))
            exposure.humidity = float(world.value("humidity", cell))
            exposure.precipitation = float(world.value("precipitation", cell))
