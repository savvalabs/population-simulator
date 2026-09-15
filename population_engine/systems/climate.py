"""ClimateSystem: the S3.1 integrator that drives the climate Fields.

This is the ``systems/``-layer half of S3.1 (CORE_DESIGN §3.1 / §5.2 / §9). It
owns NO equation and NO biome-selection algorithm. Each tick it:

1. reads the season label from ``ctx.clock`` and the per-cell ``altitude`` Field,
2. resolves already-resolved per-cell base climate values from an *injected*
   biome-provider (the D1 seam),
3. hands those + altitude + season + the shared ``ctx.rng`` to
   :class:`~population_engine.models.climate.ClimateModel.step`,
4. writes the returned temperature / humidity / precipitation into each chunk's
   climate ``Field`` interiors, and
5. refreshes ``biome_id`` as the ADR-002 downstream projection
   ``World.classify_chunk`` (computed from the climate this system just wrote;
   never re-read as a climate input, which would close a biome->climate->biome
   feedback loop).

D1 seam (``docs/open-questions/D1-biome-acquisition.md``): per-cell biome
acquisition is an *unresolved* architectural gap in CORE_DESIGN. It is NOT
solved here. The provider below is a replaceable seam -- swap it when D1 is
decided; :class:`~population_engine.models.climate.ClimateModel` and this
system's per-chunk loop are unchanged.

World coupling: this is a ``systems/`` module, so it imports ``world`` and
``models`` at runtime (CORE_DESIGN §8 soft-rule list -- systems are the
world-coupled layer). It does NOT expand ``SystemContext``: it uses only the
existing ``world`` / ``clock`` / ``rng`` slots.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, TYPE_CHECKING

import numpy as np

from ..ecs.scheduler import System, SystemContext
from ..models.climate import ClimateModel
from ..world.coords import ChunkCoord

if TYPE_CHECKING:
    from ..world.world import World

__all__ = [
    "BiomeBaseValues",
    "BiomeProvider",
    "UniformBiomeProvider",
    "ClimateSystem",
]


class BiomeBaseValues(tuple):
    """Already-resolved per-cell base climate values (the D1 seam payload).

    A trivial ``tuple`` subclass exposing named accessors so the provider
    contract is self-documenting and stable across D1 resolutions. Produced by
    a :class:`BiomeProvider`; consumed by
    :meth:`~population_engine.models.climate.ClimateModel.step`. Carrying the
    three arrays as one named object (not a loose triple) keeps the seam robust
    to argument-order changes.

    Note: this deliberately subclasses ``tuple`` (immutable, cheap) rather than
    a frozen dataclass so it stays a value object with no behaviour.
    """

    __slots__ = ()

    def __new__(cls, base_temperature, base_humidity, base_precipitation):
        return tuple.__new__(
            cls, (base_temperature, base_humidity, base_precipitation)
        )

    @property
    def base_temperature(self):
        return self[0]

    @property
    def base_humidity(self):
        return self[1]

    @property
    def base_precipitation(self):
        return self[2]


@runtime_checkable
class BiomeProvider(Protocol):
    """The D1 seam: resolve per-cell base climate values from altitude.

    A provider receives the per-cell ``altitude`` array (the natural altitude
    selector named by CORE_DESIGN §5.2) and returns the per-cell
    :class:`BiomeBaseValues` the climate model consumes. A real D1 provider
    closes over whatever it needs (the :class:`World`, the
    :class:`~population_engine.data.registry.DataRegistry`, authored
    ``BiomeData`` ranges, ...) at *construction* -- so this Protocol stays
    minimal and world-free.

    TODO(D1): CORE_DESIGN never specifies the altitude/coordinate -> BiomeData
    acquisition; see ``docs/open-questions/D1-biome-acquisition.md``. This
    Protocol is the replaceable seam; a future D1 decision supplies a real
    provider. The climate model never sees the provider.
    """

    def base_values(self, altitude: np.ndarray) -> "BiomeBaseValues":
        ...


class UniformBiomeProvider:
    """Provisional D1 stand-in (NOT a real per-cell biome acquisition).

    Returns ONE constant set of base values for every cell, ignoring altitude.
    This deliberately does NOT resolve ``BiomeData`` per cell -- D1 is
    unresolved -- so the architecture / data-flow / testability of S3.1 can be
    exercised now. Replace this provider when D1 is decided; ``ClimateModel``
    and ``ClimateSystem`` are unchanged.
    """

    def __init__(
        self,
        *,
        base_temperature: float = 20.0,
        base_humidity: float = 0.5,
        base_precipitation: float = 0.0,
    ) -> None:
        self._bt = float(base_temperature)
        self._bh = float(base_humidity)
        self._bp = float(base_precipitation)

    @property
    def base_temperature(self) -> float:
        return self._bt

    @base_temperature.setter
    def base_temperature(self, value: float) -> None:
        """Public setter so clients (UI toggles, scenarios) can force the
        base temperature between ticks without touching the private field."""
        self._bt = float(value)

    def base_values(self, altitude: np.ndarray) -> "BiomeBaseValues":
        shape = altitude.shape
        return BiomeBaseValues(
            np.full(shape, self._bt, dtype=np.float64),
            np.full(shape, self._bh, dtype=np.float64),
            np.full(shape, self._bp, dtype=np.float64),
        )


class ClimateSystem(System):
    """Drive the climate Fields from biome + season + altitude + RNG (S3.1).

    CORE_DESIGN §3.1: the #1 system. §4: stage 1 (no ``after``). §5.2 reads:
    ``Clock.now()`` (season), the altitude ``Field``, resolved biome base values
    (via the D1 provider), and ``rng``; writes the temperature / humidity /
    precipitation ``Field`` interiors, then refreshes ``biome_id`` per ADR-002.

    ``reads`` / ``writes`` are empty tuples: this system touches World *Fields*,
    not ECS components, so it declares no component access (CORE_DESIGN §8 --
    World is outside the ECS component-conflict graph; the scheduler's staging
    only considers component read/write overlap, which is none here). ``after``
    is empty: ClimateSystem is a dataflow-DAG root, so every downstream system
    that consumes the climate Fields is a transitive consumer.
    """

    name = "climate"
    reads: tuple = ()
    writes: tuple = ()
    after: tuple = ()

    def __init__(
        self,
        model: ClimateModel | None = None,
        biome_provider: "BiomeProvider | None" = None,
    ) -> None:
        # Defaults let a bare ``ClimateSystem()`` run for smoke purposes; real
        # wiring passes an explicit model + a provider resolved from authored
        # data when D1 is decided.
        self._model = model if model is not None else ClimateModel()
        self._biome_provider = (
            biome_provider
            if biome_provider is not None
            else UniformBiomeProvider()
        )

    def update(self, ctx: SystemContext) -> None:
        world: "World | None" = ctx.world
        if world is None:
            return  # nothing to drive without a world (defensive; never the case under the Engine)
        clock = ctx.clock
        season = clock.now().season if clock is not None else "dry"
        # The shared deterministic RNG. Under the Engine this is always set; a
        # bare-constructed fallback keeps a direct unit call from crashing.
        rng = ctx.rng if ctx.rng is not None else np.random.default_rng(0)

        model = self._model
        provider = self._biome_provider

        # Iterate the bounded chunk grid in a fixed (iy, ix) order so the shared
        # RNG is consumed deterministically (CORE_DESIGN §1.6). Per chunk the
        # model draws temperature -> humidity -> precipitation noise, in order.
        for iy in range(world.height_chunks):
            for ix in range(world.width_chunks):
                coord = ChunkCoord(ix, iy)
                chunk = world.chunk(coord)
                altitude = chunk.field("altitude").interior

                bases = provider.base_values(altitude)
                temperature, humidity, precipitation = model.step(
                    altitude=altitude,
                    base_temperature=bases.base_temperature,
                    base_humidity=bases.base_humidity,
                    base_precipitation=bases.base_precipitation,
                    season=season,
                    rng=rng,
                )

                # Write the climate Field interiors (the only writable surface;
                # the halo is left to the Engine's next-tick refresh_halos). The
                # ``[...] =`` assignment writes through the interior view into
                # the backing buffer; the returned arrays are fresh (no aliasing).
                chunk.field("temperature").interior[...] = temperature
                chunk.field("humidity").interior[...] = humidity
                chunk.field("precipitation").interior[...] = precipitation

                # ADR-002: ``biome_id`` is a downstream cached projection, the
                # classifier applied to the climate this system just wrote. It is
                # never re-read as a climate input (that would close a
                # biome->climate->biome feedback loop and contradict ADR-002).
                chunk.field("biome_id").interior[...] = world.classify_chunk(chunk)
