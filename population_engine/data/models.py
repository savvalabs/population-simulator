"""Immutable authored-data value objects (the ``data/`` templates).

Each dataclass is a frozen value object: one instance describes one kind of
authored game entity (a species, a biome, a plant/flora type, or a generic
resource type). They are constructed once — by the loaders or inline in tests
— stored by the :class:`~population_engine.data.registry.DataRegistry`, and
read by systems through ``ctx.data``. The data layer is pure data + validation:
it imports nothing from ``ecs``, ``world``, ``core``, RNG, or time.

Season labels (``mating_season_*``, ``season_effect`` seasons) are free-form
strings, intentionally matching the opaque labels produced by
``core.time.SeasonCalendar`` (e.g. ``"dry"`` / ``"rainy"``). The data layer does
not import time; it only carries the labels, which systems interpret later.

Validation fails **closed at construction**: a range/presence violation raises
:class:`~population_engine.data.exceptions.InvalidDataError` from
``__post_init__``, so a malformed template can never reach the registry or a
system. Defaults are chosen to be benign so a minimal
``SpeciesData("jaguar", "Jaguar")`` is well-formed. Tuple-typed fields coerce a
passed ``list`` to a ``tuple`` via :func:`object.__setattr__` so the instance is
always truly immutable (and hashable).
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import InvalidDataError

__all__ = [
    "SpeciesData",
    "BiomeData",
    "PlantData",
    "ResourceData",
]


# -- shared validators (module-scope helpers, not part of the public API) -------


def _require_str(value: object, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidDataError(f"{label} must be a non-empty str, got {value!r}")


def _require_nonneg(value: object, label: str) -> None:
    # bool is a subclass of int; reject it so True/False can't pose as 0/1.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidDataError(f"{label} must be a number, got {value!r}")
    if value < 0:
        raise InvalidDataError(f"{label} must be >= 0, got {value!r}")


def _require_range(lo: object, hi: object, label: str) -> None:
    if isinstance(lo, bool) or not isinstance(lo, (int, float)):
        raise InvalidDataError(f"{label}.min must be a number, got {lo!r}")
    if isinstance(hi, bool) or not isinstance(hi, (int, float)):
        raise InvalidDataError(f"{label}.max must be a number, got {hi!r}")
    if lo > hi:
        raise InvalidDataError(f"{label} range min ({lo}) must be <= max ({hi})")


def _require_bool(value: object, label: str) -> None:
    if not isinstance(value, bool):
        raise InvalidDataError(f"{label} must be a bool, got {value!r}")


def _require_str_tuple(value: object, label: str) -> tuple[str, ...]:
    """Coerce and validate an id-tuple; tolerate a ``list`` for ergonomics."""
    if isinstance(value, str):
        raise InvalidDataError(f"{label} must be a sequence, got a str")
    try:
        items = list(value)
    except TypeError as exc:
        raise InvalidDataError(f"{label} must be iterable, got {value!r}") from exc
    for i, item in enumerate(items):
        if not isinstance(item, str) or not item:
            raise InvalidDataError(
                f"{label}[{i}] must be a non-empty str, got {item!r}"
            )
    return tuple(items)


def _require_season_effect(pairs: object, label: str) -> tuple[tuple[str, float], ...]:
    """Validate a ``season_effect`` is a sequence of ``(str, non-neg float)`` pairs."""
    if isinstance(pairs, (str, bytes, dict)):
        raise InvalidDataError(
            f"{label} must be a sequence of (season, multiplier) pairs, got {pairs!r}"
        )
    try:
        items = list(pairs)
    except TypeError as exc:
        raise InvalidDataError(f"{label} must be iterable, got {pairs!r}") from exc
    out: list[tuple[str, float]] = []
    for i, pair in enumerate(items):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise InvalidDataError(
                f"{label}[{i}] must be a (season, multiplier) pair, got {pair!r}"
            )
        season, mult = pair
        if not isinstance(season, str) or not season:
            raise InvalidDataError(
                f"{label}[{i}] season must be a non-empty str, got {season!r}"
            )
        if isinstance(mult, bool) or not isinstance(mult, (int, float)):
            raise InvalidDataError(
                f"{label}[{i}] multiplier must be a number, got {mult!r}"
            )
        if mult < 0:
            raise InvalidDataError(
                f"{label}[{i}] multiplier must be >= 0, got {mult!r}"
            )
        out.append((season, float(mult)))
    return tuple(out)


# ---------------------------------------------------------------------------- #
# Species
# ---------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SpeciesData:
    """Authored parameters of one species (the legacy "class parameter" set).

    ``id`` is the stable string looked up via ``ctx.data.species(id)`` and held
    by a future ``SpeciesRef`` component. ``consumes`` references resource *and*
    prey-species ids; ``diet_type`` is a free-form label interpreted by foraging
    models. The numeric defaults are benign so a minimal
    ``SpeciesData("jaguar", "Jaguar")`` is well-formed; real content overrides
    them via the loader.
    """

    id: str
    name: str
    # Diet defaults (the per-instance Diet component is derived from these).
    diet_type: str = "herbivore"
    consumes: tuple[str, ...] = ()

    # Vital caps (floats — they integrate an ODE each tick).
    max_hp: float = 100.0
    max_energy: float = 100.0
    max_hunger: float = 100.0
    max_thirst: float = 100.0
    # Age (ticks).
    max_age: int = 1000

    # Metabolism.
    metabolic_rate: float = 1.0
    base_energy_cost: float = 1.0

    # Motion / perception.
    speed: float = 1.0
    flight_speed: float = 0.0
    swim_speed: float = 0.0
    vision_range: float = 1.0
    territory_size: float = 1.0

    # Foraging skill.
    hunt_skill: float = 0.0
    escape_skill: float = 0.0
    stealth: float = 0.0
    strength: float = 0.0

    # Reproduction.
    reproduction_rate: float = 0.5
    gestation_time: int = 100
    litter_size: int = 1
    mating_season_start: str = ""
    mating_season_end: str = ""
    monogamous: bool = False
    parental_care_duration: int = 0
    min_reproduction_age: int = 100

    # Tolerances (free-form units; ranges are min <= max).
    temperature_tolerance_min: float = -10.0
    temperature_tolerance_max: float = 45.0
    humidity_tolerance_min: float = 0.0
    humidity_tolerance_max: float = 1.0

    # Other needs / defences.
    water_needs: float = 1.0
    disease_resistance: float = 1.0
    infant_survival_rate: float = 0.5

    def __post_init__(self) -> None:
        _require_str(self.id, "SpeciesData.id")
        _require_str(self.name, "SpeciesData.name")
        if not isinstance(self.diet_type, str):
            raise InvalidDataError(f"diet_type must be a str, got {self.diet_type!r}")
        if self.mating_season_start != "" or self.mating_season_end != "":
            for label in ("mating_season_start", "mating_season_end"):
                val = getattr(self, label)
                if not isinstance(val, str):
                    raise InvalidDataError(f"{label} must be a str, got {val!r}")
        _require_bool(self.monogamous, "SpeciesData.monogamous")
        object.__setattr__(self, "consumes", _require_str_tuple(self.consumes, "SpeciesData.consumes"))
        for label, value in (
            ("max_hp", self.max_hp),
            ("max_energy", self.max_energy),
            ("max_hunger", self.max_hunger),
            ("max_thirst", self.max_thirst),
            ("metabolic_rate", self.metabolic_rate),
            ("base_energy_cost", self.base_energy_cost),
            ("speed", self.speed),
            ("flight_speed", self.flight_speed),
            ("swim_speed", self.swim_speed),
            ("vision_range", self.vision_range),
            ("territory_size", self.territory_size),
            ("hunt_skill", self.hunt_skill),
            ("escape_skill", self.escape_skill),
            ("stealth", self.stealth),
            ("strength", self.strength),
            ("reproduction_rate", self.reproduction_rate),
            ("water_needs", self.water_needs),
            ("disease_resistance", self.disease_resistance),
            ("infant_survival_rate", self.infant_survival_rate),
        ):
            _require_nonneg(value, f"SpeciesData.{label}")
        for label, value in (
            ("max_age", self.max_age),
            ("gestation_time", self.gestation_time),
            ("litter_size", self.litter_size),
            ("parental_care_duration", self.parental_care_duration),
            ("min_reproduction_age", self.min_reproduction_age),
        ):
            _require_nonneg(value, f"SpeciesData.{label}")
        _require_range(
            self.temperature_tolerance_min,
            self.temperature_tolerance_max,
            "SpeciesData.temperature_tolerance",
        )
        _require_range(
            self.humidity_tolerance_min,
            self.humidity_tolerance_max,
            "SpeciesData.humidity_tolerance",
        )


# ---------------------------------------------------------------------------- #
# Biome
# ---------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BiomeData:
    """Authored biome template (replaces legacy ``biomes.json`` metadata).

    Distinct from :class:`population_engine.world.biome.Biome`, which is the
    runtime cell-classifier (altitude/temperature/humidity ranges only).
    ``BiomeData`` carries the *authored* extras systems need: carrying capacity,
    base climate, supported resource ids, and a biomass regen modifier. The
    range fields mirror ``world.Biome``'s inclusive-min / exclusive-max
    semantics (first match wins) so a ``BiomeData`` can seed a world biome table.
    """

    id: str
    name: str
    carrying_capacity: float = 100.0

    # Base climate (the value a static cell of this biome tends toward).
    base_temperature: float = 20.0
    base_humidity: float = 0.5
    base_precipitation: float = 0.0

    # Classification ranges (inclusive-min, exclusive-max; min <= max).
    min_altitude: float = 0.0
    max_altitude: float = 6000.0
    min_temperature: float = -20.0
    max_temperature: float = 50.0
    min_humidity: float = 0.0
    max_humidity: float = 1.0

    # Authored links (ids into the resource registry).
    supported_resources: tuple[str, ...] = ()
    regen_modifier: float = 1.0

    def __post_init__(self) -> None:
        _require_str(self.id, "BiomeData.id")
        _require_str(self.name, "BiomeData.name")
        _require_nonneg(self.carrying_capacity, "BiomeData.carrying_capacity")
        _require_nonneg(self.base_precipitation, "BiomeData.base_precipitation")
        _require_nonneg(self.regen_modifier, "BiomeData.regen_modifier")
        object.__setattr__(
            self,
            "supported_resources",
            _require_str_tuple(self.supported_resources, "BiomeData.supported_resources"),
        )
        if not (0.0 <= self.base_humidity <= 1.0):
            raise InvalidDataError(
                f"base_humidity must be in [0, 1], got {self.base_humidity!r}"
            )
        for label, lo, hi in (
            ("altitude", self.min_altitude, self.max_altitude),
            ("temperature", self.min_temperature, self.max_temperature),
            ("humidity", self.min_humidity, self.max_humidity),
        ):
            _require_range(lo, hi, f"BiomeData.{label}")


# ---------------------------------------------------------------------------- #
# Plant (flora / vegetation template)
# ---------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlantData:
    """Authored vegetation template.

    A plant grows within ``supported_biomes`` (biome ids), regenerates biomass
    each tick at ``regeneration_rate`` (modified per season via
    ``season_effect``), and provides ``nutritional_value`` with a ``toxicity``
    cost when consumed. Plants are the herbivory substrate; the
    :class:`ResourceSystem` (S3.2) consumes this template to drive biomass
    Fields.
    """

    id: str
    name: str
    max_biomass: float = 100.0
    regeneration_rate: float = 0.1
    nutritional_value: float = 1.0
    toxicity: float = 0.0
    supported_biomes: tuple[str, ...] = ()
    season_effect: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        _require_str(self.id, "PlantData.id")
        _require_str(self.name, "PlantData.name")
        for label, value in (
            ("max_biomass", self.max_biomass),
            ("regeneration_rate", self.regeneration_rate),
            ("nutritional_value", self.nutritional_value),
            ("toxicity", self.toxicity),
        ):
            _require_nonneg(value, f"PlantData.{label}")
        object.__setattr__(
            self,
            "supported_biomes",
            _require_str_tuple(self.supported_biomes, "PlantData.supported_biomes"),
        )
        object.__setattr__(
            self,
            "season_effect",
            _require_season_effect(self.season_effect, "PlantData.season_effect"),
        )


# ---------------------------------------------------------------------------- #
# Resource (generic consumable type, e.g. water)
# ---------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResourceData:
    """Authored generic resource type (non-plant consumables such as water).

    Distinct from :class:`PlantData` (vegetation has a biome-tied biomass
    substrate); a generic resource is a per-cell amount that regenerates and can
    be drunk/consumed. ``season_effect`` scales regeneration by season label.
    """

    id: str
    name: str
    max_amount: float = 100.0
    regeneration_rate: float = 0.1
    nutritional_value: float = 0.0
    toxicity: float = 0.0
    season_effect: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        _require_str(self.id, "ResourceData.id")
        _require_str(self.name, "ResourceData.name")
        for label, value in (
            ("max_amount", self.max_amount),
            ("regeneration_rate", self.regeneration_rate),
            ("nutritional_value", self.nutritional_value),
            ("toxicity", self.toxicity),
        ):
            _require_nonneg(value, f"ResourceData.{label}")
        object.__setattr__(
            self,
            "season_effect",
            _require_season_effect(self.season_effect, "ResourceData.season_effect"),
        )
