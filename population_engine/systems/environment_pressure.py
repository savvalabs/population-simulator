"""EnvironmentPressureSystem: cold stress from exposure vs. phenotype (S3).

Reads the entity's :class:`CellExposure` (written once per tick by
``ExposureSystem``, the §3.1 decoupling hinge) — this system is fully
**world-free**: it never touches ``ctx.world``. That makes it unit-testable
with synthetic components and keeps the entity pipeline decoupled from the
chunk substrate.

Thermal-stress math (comfort base 20.0 °C), unchanged from the pre-hinge
version:

* ``min_tolerable = 20.0 - phenotype.cold_resistance``
* if ``exposure.temperature < min_tolerable``:
  ``penalty = int(min_tolerable - exposure.temperature)`` and
  ``energy.current_energy -= penalty``. Energy may go negative;
  ``DeathSystem`` reaps anything ``<= 0``.
"""

from __future__ import annotations

from ..ecs.components import CellExposure, EnergyComponent, PhenotypeComponent
from ..ecs.scheduler import System, SystemContext

__all__ = ["EnvironmentPressureSystem"]

#: Neutral comfort temperature in °C. Cold tolerance = comfort - cold_resistance.
COMFORT_TEMPERATURE: float = 20.0


class EnvironmentPressureSystem(System):
    """Apply cold-stress energy penalties from the entity's own exposure.

    Iterates entities carrying ``CellExposure`` + ``PhenotypeComponent`` +
    ``EnergyComponent`` via the registry query (deterministic archetype
    order). Entities lacking any of the three are ignored. Mutates only
    ``EnergyComponent.current_energy`` in place; never destroys entities —
    ``DeathSystem`` owns removal.
    """

    name = "environment_pressure"
    reads: tuple = (PhenotypeComponent, CellExposure, EnergyComponent)
    writes: tuple = (EnergyComponent,)
    # Only component deps remain: exposure (written by ExposureSystem) feeds
    # us; the scheduler orders us via the component read/write conflict with
    # exposure's write... but conflict-order alone is not a guarantee for all
    # scheduler policies, and clarity costs nothing. Declare it explicitly.
    after: tuple = ("exposure",)

    def update(self, ctx: SystemContext) -> None:
        query = ctx.registry.query(
            CellExposure, PhenotypeComponent, EnergyComponent
        )
        for _entity, exposure, phenotype, energy in query:
            min_tolerable = COMFORT_TEMPERATURE - phenotype.cold_resistance
            cell_temp = exposure.temperature
            if cell_temp < min_tolerable:
                penalty = int(min_tolerable - cell_temp)
                energy.current_energy -= penalty
