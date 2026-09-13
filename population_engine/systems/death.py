"""DeathSystem: remove entities whose energy reaches zero (the GC pass).

A dead entity (``current_energy <= 0`` — written by ``EnvironmentPressureSystem``
and, later, metabolism) is destroyed wholesale: its components are dropped and
its slot recycled by :meth:`Registry.destroy_entity`.

Structural-change note (ADR-004): systems must not mutate archetype structure
*while the scheduler iterates them*; despawns are meant to be queued and
applied at the engine's structural-commit phase. The engine's structural
request queue exists but its enqueue API has not landed yet (mechanics
scheduled with the rest of S3). Until then this system uses the safe interim
pattern: it **collects** dead entities during the (exhausted) query and only
then destroys them, so archetypes are never mutated mid-iteration. When the
structural-request API lands, replace the destroy loop with enqueued despawn
requests — behaviour for callers is unchanged.

Ordering: declare ``after=("environment_pressure",)``-style writers as needed
when wiring the scheduler; the system itself declares no ``after`` because its
only input is a component it does not write.
"""

from __future__ import annotations

from ..ecs.components import EnergyComponent
from ..ecs.scheduler import System, SystemContext

__all__ = ["DeathSystem"]


class DeathSystem(System):
    """Destroy every entity whose ``EnergyComponent.current_energy <= 0``.

    Reads-only by component classification (``writes=()``): destruction is a
    structural change, not a component mutation, so it stays out of the
    scheduler's read/write conflict graph. Deaths are collected first and
    applied after the query iterator is exhausted — never during iteration
    (see module docstring, ADR-004 interim pattern).
    """

    name = "death"
    reads: tuple = (EnergyComponent,)
    writes: tuple = ()
    after: tuple = ()

    def update(self, ctx: SystemContext) -> None:
        registry = ctx.registry
        # Phase 1: collect — exhaust the query BEFORE any structural change.
        dead = [
            entity
            for entity, energy in registry.query(EnergyComponent)
            if energy.current_energy <= 0
        ]
        # Phase 2: destroy — safe now; the query iterator is finished.
        for entity in dead:
            registry.destroy_entity(entity)
