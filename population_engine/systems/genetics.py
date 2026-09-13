"""GeneticsSystem: express the genome into the phenotype each tick.

Separates the heritable ADN (:class:`GenomeComponent`) from the physical stats
(:class:`PhenotypeComponent`) so mutations can alter genes dynamically while
the phenotype stays a pure, recomputed projection — never an independent state.

This is a **world-free** system (CORE_DESIGN §8): it reads and writes only ECS
components via the registry query engine, in deterministic archetype order. It
declares no ``after``: its only dependency is component data.

Expression rules (constant factors, per the design spec):

* ``cold_resistance = fur_thickness * 10.0``
* ``speed           = leg_length   *  1.5``
* ``camouflage      = 0.8`` if ``fur_color == "white"``, ``0.4`` if
  ``"brown"``, else ``0.1``
"""

from __future__ import annotations

from ..ecs.components import GenomeComponent, PhenotypeComponent
from ..ecs.scheduler import System, SystemContext

__all__ = ["GeneticsSystem"]

# Camouflage value per fur colour; unknown colours fall back to _CAMO_DEFAULT.
_CAMOUFLAGE_BY_COLOR: dict[str, float] = {
    "white": 0.8,
    "brown": 0.4,
}
_CAMOUFLAGE_DEFAULT: float = 0.1

_COLD_RESISTANCE_FACTOR: float = 10.0
_SPEED_FACTOR: float = 1.5


class GeneticsSystem(System):
    """Express :class:`GenomeComponent` genes into :class:`PhenotypeComponent`.

    Iterates every entity carrying **both** components (via
    ``registry.query(GenomeComponent, PhenotypeComponent)``) and rewrites the
    phenotype in place from the current gene values. Mutation systems touch
    only the genome; this system is the single writer of the phenotype, which
    keeps the phenotype a consistent derived view of the ADN.
    """

    name = "genetics"
    reads: tuple = (GenomeComponent,)
    writes: tuple = (PhenotypeComponent,)
    after: tuple = ()

    def update(self, ctx: SystemContext) -> None:
        query = ctx.registry.query(GenomeComponent, PhenotypeComponent)
        for _entity, genome, phenotype in query:
            genes = genome.genes
            phenotype.cold_resistance = (
                float(genes.get("fur_thickness", 0)) * _COLD_RESISTANCE_FACTOR
            )
            phenotype.speed = float(genes.get("leg_length", 0)) * _SPEED_FACTOR
            phenotype.camouflage = _CAMOUFLAGE_BY_COLOR.get(
                genes.get("fur_color"), _CAMOUFLAGE_DEFAULT
            )
