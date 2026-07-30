"""The bundled-data composition point.

A single function — :func:`load_default_registry` — that turns the shipped JSON
in ``sources/`` into a populated :class:`~population_engine.data.registry.
DataRegistry` by way of the stateless :mod:`.loader`. It is the only place that
knows where the authored files live; everything else (type coercion + range
validation) stays in the loaders and the models' ``__post_init__``, and all
storage stays in the registry. This module therefore owns **no state of its
own** and imports neither ``ecs`` nor ``world`` (the ``data/`` layer invariant).

The shipped files are JSON *lists of records* (one record per entity), each
shaped exactly as the matching ``*_from_dict`` loader expects:

* ``sources/species.json``   → :class:`~population_engine.data.models.SpeciesData`
* ``sources/biomes.json``    → :class:`~population_engine.data.models.BiomeData`
* ``sources/plants.json``    → :class:`~population_engine.data.models.PlantData`
* ``sources/resources.json`` → :class:`~population_engine.data.models.ResourceData`

Call ``load_default_registry()`` once at engine construction and pass the result
to :class:`~population_engine.core.engine.Engine` as ``data`` (so it reaches
systems as ``ctx.data``). Validation fails closed: a malformed record raises
:class:`~population_engine.data.exceptions.InvalidDataError` before any
insertion, leaving the registry empty.
"""

from __future__ import annotations

from pathlib import Path

from .loader import (
    biome_from_file,
    plant_from_file,
    resource_from_file,
    species_from_file,
)
from .registry import DataRegistry

__all__ = ["load_default_registry", "BUNDLED_SOURCES_DIR"]

#: Directory holding the shipped authored JSON (sibling of this module).
BUNDLED_SOURCES_DIR: Path = Path(__file__).resolve().parent / "sources"

# Load order matters only for human-readable ``all_*`` iteration, not for
# correctness (each kind is an independent store). Biomes → resources → plants
# → species mirrors the dependency direction systems will read them in
# (environment before the flora that lives in it before the fauna that consume
# both), which keeps ``all_*`` snapshots in a natural order for diagnostics.
_LOADERS: tuple[tuple[str, ...], ...] = (
    ("biomes.json", "biome_from_file", "load_biomes"),
    ("resources.json", "resource_from_file", "load_resources"),
    ("plants.json", "plant_from_file", "load_plants"),
    ("species.json", "species_from_file", "load_species"),
)


def load_default_registry() -> DataRegistry:
    """Load every bundled source into a fresh :class:`DataRegistry`.

    Reads the shipped JSON in ``sources/`` through the stateless loaders and
    populates the registry kind by kind. Each ``load_*`` is atomic (duplicate
    ids reject the whole batch before any insertion), and each record is
    validated by its model's ``__post_init__`` at construction — so a malformed
    bundled source surfaces as a single :class:`InvalidDataError` (or
    :class:`~population_engine.data.exceptions.DuplicateDataError`) and the
    registry is left empty rather than half-loaded.
    """
    reg = DataRegistry()
    reg.load_biomes(biome_from_file(BUNDLED_SOURCES_DIR / "biomes.json"))
    reg.load_resources(resource_from_file(BUNDLED_SOURCES_DIR / "resources.json"))
    reg.load_plants(plant_from_file(BUNDLED_SOURCES_DIR / "plants.json"))
    reg.load_species(species_from_file(BUNDLED_SOURCES_DIR / "species.json"))
    return reg
