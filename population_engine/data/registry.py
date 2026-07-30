"""The data registry: the single source of truth for authored game data.

:class:`DataRegistry` stores the frozen value objects of :mod:`.models` keyed by
stable string id, validates uniqueness at load, and exposes read-only lookup.
It is the only place static game data lives; no other subsystem reads JSON/YAML
directly — it goes through this registry (and through the :mod:`.loader` that
feeds it).

Design contract (from CORE_DESIGN §7):

* **Immutable at runtime.** Internal id→model dicts are private; the public
  surface exposes only ``load_*`` (setup-phase population), single-id getters,
  ``has_*``, and ``all_*`` (each returning a fresh immutable ``tuple`` snapshot
  in insertion order). A handle to a stored model is the frozen object itself;
  there is no path to mutate the registry's contents after load.
* **Atomic loads.** ``load_*`` detects every duplicate id — both within the
  batch and against ids already loaded — *before* inserting anything, so a
  rejected batch leaves the registry unchanged (never half-populated).
* **No coupling.** The registry imports nothing from ``ecs`` / ``world`` /
  ``core`` / RNG / time; it is pure storage + lookup.

The registry is injected onto :class:`SystemContext` as ``ctx.data`` (forward
referenced as ``"DataRegistry"`` in ``ecs/scheduler.py`` since S0).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .exceptions import DuplicateDataError, UnknownDataError
from .models import BiomeData, PlantData, ResourceData, SpeciesData

__all__ = ["DataRegistry"]

# Map each load/get/has/all kind to (model class, internal-dict attr name).
_KINDS: dict[str, tuple[type, str]] = {
    "species": (SpeciesData, "_species"),
    "biome": (BiomeData, "_biomes"),
    "plant": (PlantData, "_plants"),
    "resource": (ResourceData, "_resources"),
}


class DataRegistry:
    """Read-only-by-convention store of authored templates, keyed by string id."""

    __slots__ = ("_species", "_biomes", "_plants", "_resources")

    def __init__(self) -> None:
        self._species: dict[str, SpeciesData] = {}
        self._biomes: dict[str, BiomeData] = {}
        self._plants: dict[str, PlantData] = {}
        self._resources: dict[str, ResourceData] = {}

    # -- setup: load (atomic, dup-detecting) -----------------------------------

    def load_species(self, items: Iterable[SpeciesData]) -> None:
        """Add species by id; raise :class:`DuplicateDataError` on any clash."""
        self._load("species", list(items))

    def load_biomes(self, items: Iterable[BiomeData]) -> None:
        """Add biomes by id; raise :class:`DuplicateDataError` on any clash."""
        self._load("biome", list(items))

    def load_plants(self, items: Iterable[PlantData]) -> None:
        """Add plants by id; raise :class:`DuplicateDataError` on any clash."""
        self._load("plant", list(items))

    def load_resources(self, items: Iterable[ResourceData]) -> None:
        """Add resources by id; raise :class:`DuplicateDataError` on any clash."""
        self._load("resource", list(items))

    # -- lookup: single getter + presence -------------------------------------

    def species(self, id: str) -> SpeciesData:
        """The species template for *id*; :class:`UnknownDataError` if absent."""
        return self._get("species", id)

    def biome(self, id: str) -> BiomeData:
        """The biome template for *id*; :class:`UnknownDataError` if absent."""
        return self._get("biome", id)

    def plant(self, id: str) -> PlantData:
        """The plant template for *id*; :class:`UnknownDataError` if absent."""
        return self._get("plant", id)

    def resource(self, id: str) -> ResourceData:
        """The resource template for *id*; :class:`UnknownDataError` if absent."""
        return self._get("resource", id)

    def has_species(self, id: str) -> bool:
        """True iff a species template with *id* is loaded."""
        return id in self._species

    def has_biome(self, id: str) -> bool:
        """True iff a biome template with *id* is loaded."""
        return id in self._biomes

    def has_plant(self, id: str) -> bool:
        """True iff a plant template with *id* is loaded."""
        return id in self._plants

    def has_resource(self, id: str) -> bool:
        """True iff a resource template with *id* is loaded."""
        return id in self._resources

    # -- inspection: immutable snapshots in insertion order --------------------

    def all_species(self) -> tuple[SpeciesData, ...]:
        """Snapshot of all species in load order."""
        return tuple(self._species.values())

    def all_biomes(self) -> tuple[BiomeData, ...]:
        """Snapshot of all biomes in load order."""
        return tuple(self._biomes.values())

    def all_plants(self) -> tuple[PlantData, ...]:
        """Snapshot of all plants in load order."""
        return tuple(self._plants.values())

    def all_resources(self) -> tuple[ResourceData, ...]:
        """Snapshot of all resources in load order."""
        return tuple(self._resources.values())

    # -- internals ------------------------------------------------------------

    def _store(self, kind: str) -> dict[str, Any]:
        return getattr(self, _KINDS[kind][1])  # type: ignore[no-any-return]

    def _load(self, kind: str, items: list[Any]) -> None:
        model_cls = _KINDS[kind][0]
        store = self._store(kind)
        # Validate type + uniqueness fully BEFORE writing anything.
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, model_cls):
                raise TypeError(
                    f"{kind}: expected {model_cls.__name__} instances, "
                    f"got {type(item).__name__}"
                )
            if item.id in seen:
                raise DuplicateDataError(
                    f"{kind}: duplicate id {item.id!r} within this load batch"
                )
            if item.id in store:
                raise DuplicateDataError(
                    f"{kind}: id {item.id!r} already loaded"
                )
            seen.add(item.id)
        for item in items:
            store[item.id] = item

    def _get(self, kind: str, id: str) -> Any:
        store = self._store(kind)
        if id in store:
            return store[id]
        raise UnknownDataError(f"{kind}: unknown id {id!r}")
