"""The data subsystem: immutable authored templates + the :class:`DataRegistry`.

``data/`` is the single source of truth for static game data — species, biomes,
plant/flora, and resource definitions — loaded once (from JSON via the
:mod:`.loader`, or inline in tests) into a :class:`DataRegistry` and then read
by systems through ``ctx.data`` by stable string id. No other subsystem reads
source files directly; everything goes through the registry. Use
:func:`load_default_registry` to build a registry from the shipped bundled
sources in ``sources/`` (the engine's default ``ctx.data``); tests build
registries from inline dicts via the ``load_*`` setup methods.

Layer contract (CORE_DESIGN §6–§7):

* **Pure data + validation.** This subpackage imports nothing from ``ecs``,
  ``world``, ``core``, RNG, or time. Season labels are opaque free-form strings
  carried here and interpreted by systems later.
* **Frozen value objects** (:class:`SpeciesData`, :class:`BiomeData`,
  :class:`PlantData`, :class:`ResourceData`) constructed fail-closed by the
  :class:`~.exceptions.InvalidDataError` validation in each ``__post_init__``.
* **Immutable store.** :class:`DataRegistry` exposes only ``load_*`` (setup),
  single-id getters, ``has_*``, and ``all_*`` (immutable ``tuple`` snapshots in
  load order); internal dicts are private. Loads are atomic — a duplicate-id
  batch is rejected before any insertion.
"""

from __future__ import annotations

from .exceptions import (
    DataRegistryError,
    DuplicateDataError,
    InvalidDataError,
    UnknownDataError,
)
from .bundled import load_default_registry
from .loader import (
    biome_from_dict,
    biome_from_file,
    plant_from_dict,
    plant_from_file,
    resource_from_dict,
    resource_from_file,
    species_from_dict,
    species_from_file,
)
from .models import BiomeData, PlantData, ResourceData, SpeciesData
from .registry import DataRegistry

__all__ = [
    # exceptions
    "DataRegistryError",
    "DuplicateDataError",
    "UnknownDataError",
    "InvalidDataError",
    # models
    "SpeciesData",
    "BiomeData",
    "PlantData",
    "ResourceData",
    # registry
    "DataRegistry",
    # composition: build a registry from the bundled shipped sources
    "load_default_registry",
    # loaders
    "species_from_dict",
    "biome_from_dict",
    "plant_from_dict",
    "resource_from_dict",
    "species_from_file",
    "biome_from_file",
    "plant_from_file",
    "resource_from_file",
]
