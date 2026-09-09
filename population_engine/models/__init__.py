"""The ``models/`` layer: pure simulation equations (no ECS, no world, no data).

``models/`` holds the mathematical core of the simulation — plain functions
that map integration state and parameters to per-tick deltas (or to the
refreshed field values they integrate). A model is *behaviour from parameters*:
a deterministic function of its explicit inputs, holding no mutable state and
performing no side effects. The thin ``systems/`` integrator that owns a model
is responsible for pulling state in and pushing deltas out; the model itself is
therefore fully unit-testable with synthetic arrays and no engine at all.

Layer contract (CORE_DESIGN §1.2, §8):

* **World-free / data-loader-free / ECS-free at runtime.** A model imports
  nothing from ``world``, ``ecs``, ``core``, the RNG/time singletons, or the
  ``data`` loaders. Authored constants enter a model only as *explicit
  arguments* (for example per-cell, already-resolved biome base values), never
  via a registry lookup performed inside the model. This keeps the whole
  equation layer unit-testable without chunks, a registry, or a clock.
* **Pure.** A model is a function of its inputs; it holds no mutable state and
  performs no I/O. Determinism is a property of passing identical inputs
  (including the same RNG draw stream), not of any hidden global order.
* **Equations only; no orchestration.** Models do not read or write ``Field``
  interiors, do not refresh the halo, do not queue structural changes, and do
  not emit events. All of that is the integrator's job.

This package is first populated in S3. Its first module — the climate equation
:mod:`population_engine.models.climate`, consumed by
:class:`~population_engine.systems.climate.ClimateSystem` — lands in S3.1. Its
equations are deliberately provisional (D2–D5 open); see the module and
``docs/open-questions/D1-biome-acquisition.md``.
"""

from __future__ import annotations

from .climate import ClimateModel, ClimateParams

# The first module (``climate``) lands in S3.1. Re-exported so callers reach the
# equation as ``from population_engine.models import ClimateModel`` without
# coupling to the module path; the integrator imports it by module path.
__all__ = ["ClimateModel", "ClimateParams"]
