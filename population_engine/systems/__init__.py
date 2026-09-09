"""ECS systems implementing simulation behaviour (climate, metabolism, ...).

A system is a thin integrator: it pulls integration state in (ECS components,
World Fields, the Clock, the shared RNG), calls a pure
:class:`~population_engine.models` equation with explicit arguments, and pushes
deltas / refreshed fields back out. The system owns NO equation and NO authored
constant; the equation lives in :mod:`population_engine.models`. Per CORE_DESIGN
§8, ``systems/`` is the world-coupled layer: it may import ``world``,
``models``, and ``data`` at runtime (unlike ``models/`` / ``ecs/`` / ``data/`` /
``core/``, which stay world-free).

S3.1 lands :mod:`population_engine.systems.climate`
(:class:`~population_engine.systems.climate.ClimateSystem`), the #1 core system.
"""

from __future__ import annotations

from .climate import (
    BiomeBaseValues,
    BiomeProvider,
    ClimateSystem,
    UniformBiomeProvider,
)

__all__ = [
    "BiomeBaseValues",
    "BiomeProvider",
    "ClimateSystem",
    "UniformBiomeProvider",
]
