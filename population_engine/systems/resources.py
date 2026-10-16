"""ResourceSystem: plant biomass regrowth per cell (trophic base of the Ñeque
ecosystem).

Each tick, every world cell regenerates biomass according to its local climate:

* ``growth = BASE_GROWTH * temp_factor * rain_factor * (1 - deforestation)``
* ``temp_factor = clamp(cell_temperature / 20.0, 0, 1.2)`` — peak near 20 °C,
  freezing stops growth.
* ``rain_factor = 0.2 + 0.8 * humidity`` — some growth even without rain.
* ``biomass`` is clamped to ``[0, MAX_BIOMASS]``.

``deforestation`` (0..1) comes from the human-pressure levers: at 1.0 the
world stops regenerating entirely (tala masiva).

World-coupled by contract (AGENTS.md allows Resource among the world-aware
systems). Deterministic: no RNG consumption, chunk iteration in fixed order.
"""

from __future__ import annotations

from ..ecs.scheduler import System, SystemContext

__all__ = ["ResourceSystem", "BASE_GROWTH", "MAX_BIOMASS"]

BASE_GROWTH: float = 2.0
MAX_BIOMASS: float = 100.0


class ResourceSystem(System):
    """Regrow the ``biomass`` Field from temperature + humidity."""

    name = "resources"
    reads: tuple = ()
    writes: tuple = ()
    # Reads temperature/humidity written by ClimateSystem: non-component dep.
    after: tuple = ("climate",)

    def __init__(self, deforestation_getter=None) -> None:
        # ``deforestation_getter``: callable -> float in [0,1], injected from
        # the human-pressure levers. Defaults to 0 (no deforestation).
        self._deforestation_getter = deforestation_getter or (lambda: 0.0)

    def update(self, ctx: SystemContext) -> None:
        world = ctx.world
        if world is None:
            return
        deforestation = max(0.0, min(1.0, float(self._deforestation_getter())))
        from ..world.coords import ChunkCoord

        for iy in range(world.height_chunks):
            for ix in range(world.width_chunks):
                chunk = world.chunk(ChunkCoord(ix, iy))
                temp = chunk.field("temperature").interior
                hum = chunk.field("humidity").interior
                bio = chunk.field("biomass").interior

                temp_factor = (temp / 20.0).clip(0.0, 1.2)
                rain_factor = 0.2 + 0.8 * hum
                growth = BASE_GROWTH * temp_factor * rain_factor * (1.0 - deforestation)
                bio[...] = (bio + growth).clip(0.0, MAX_BIOMASS)
