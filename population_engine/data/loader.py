"""Stateless loaders: raw records → ``data/`` model instances.

The loader converts authored records (plain dicts read from a JSON list, or
inline dicts in tests) into the frozen value objects of :mod:`.models`. It owns
**no state**: it never stores anything, never imports ``ecs`` / ``world`` /
``core``, and never touches the registry. Range validation stays in the models'
``__post_init__``; the loader is responsible for **type coercion**, requiring
the ``id`` / ``name`` keys, recognising both ``{"season": mult}`` mappings and
``[[season, mult], ...]`` lists for ``season_effect``, and sorting season
effects by label so two equivalent authorings produce identical model bytes
(determinism at load time).

Public surface: ``{species,biome,plant,resource}_from_dict`` and
``{species,biome,plant,resource}_from_file``. ``*_from_file`` expects a top-level
JSON **list** of records (one record per entity).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .exceptions import InvalidDataError
from .models import BiomeData, PlantData, ResourceData, SpeciesData

__all__ = [
    "species_from_dict",
    "biome_from_dict",
    "plant_from_dict",
    "resource_from_dict",
    "species_from_file",
    "biome_from_file",
    "plant_from_file",
    "resource_from_file",
]


# -- internal helpers --------------------------------------------------------

_MISSING = object()


def _require_mapping(d: object, where: str) -> Mapping[str, Any]:
    if not isinstance(d, Mapping):
        raise InvalidDataError(f"{where}: expected a mapping/record, got {d!r}")
    return d  # type: ignore[return-value]


def _req_str(d: Mapping[str, Any], key: str, where: str) -> str:
    if key not in d:
        raise InvalidDataError(f"{where}: missing required key {key!r}")
    v = d[key]
    if not isinstance(v, str) or not v:
        raise InvalidDataError(f"{where}.{key} must be a non-empty str, got {v!r}")
    return v


def _opt_str(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d:
        return _MISSING
    v = d[key]
    if not isinstance(v, str):
        raise InvalidDataError(f"{where}.{key} must be a str, got {v!r}")
    return v


def _opt_float(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d:
        return _MISSING
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise InvalidDataError(f"{where}.{key} must be a number, got {v!r}")
    return float(v)


def _opt_int(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d:
        return _MISSING
    v = d[key]
    # Accept ints (and ints that came through JSON); reject floats/bools.
    if isinstance(v, bool) or not isinstance(v, int) or isinstance(v, float):
        raise InvalidDataError(f"{where}.{key} must be an int, got {v!r}")
    return int(v)


def _opt_bool(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d:
        return _MISSING
    v = d[key]
    if not isinstance(v, bool):
        raise InvalidDataError(f"{where}.{key} must be a bool, got {v!r}")
    return v


def _opt_tuplestr(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d:
        return _MISSING
    v = d[key]
    if isinstance(v, str):
        raise InvalidDataError(f"{where}.{key} must be a sequence, got a str")
    try:
        items = list(v)
    except TypeError as exc:
        raise InvalidDataError(f"{where}.{key} must be iterable, got {v!r}") from exc
    for i, item in enumerate(items):
        if not isinstance(item, str) or not item:
            raise InvalidDataError(
                f"{where}.{key}[{i}] must be a non-empty str, got {item!r}"
            )
    return tuple(items)


def _opt_season(d: Mapping[str, Any], key: str, where: str) -> Any:
    """Accept ``{season: mult}`` **or** ``[[season, mult], ...]``; sort by season."""
    if key not in d:
        return _MISSING
    raw = d[key]
    if isinstance(raw, Mapping):
        items = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise InvalidDataError(
            f"{where}.{key}: expected a mapping or list of pairs, got {raw!r}"
        )
    pairs: list[tuple[str, Any]] = []
    for i, pair in enumerate(items):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise InvalidDataError(
                f"{where}.{key}[{i}]: expected (season, multiplier), got {pair!r}"
            )
        season, mult = pair
        if not isinstance(season, str) or not season:
            raise InvalidDataError(
                f"{where}.{key}[{i}]: season must be a non-empty str, got {season!r}"
            )
        pairs.append((season, mult))
    # Deterministic order regardless of JSON authoring order.
    pairs.sort(key=lambda p: p[0])
    return tuple(pairs)


def _put(kw: dict[str, Any], key: str, value: Any) -> None:
    """Record a coerced value into kwargs, skipping absent field-options."""
    if value is _MISSING:
        return
    kw[key] = value


# -- per-model field tables --------------------------------------------------

_SPECIES_FLOATS = (
    "max_hp", "max_energy", "max_hunger", "max_thirst",
    "metabolic_rate", "base_energy_cost",
    "speed", "flight_speed", "swim_speed", "vision_range", "territory_size",
    "hunt_skill", "escape_skill", "stealth", "strength",
    "reproduction_rate",
    "temperature_tolerance_min", "temperature_tolerance_max",
    "humidity_tolerance_min", "humidity_tolerance_max",
    "water_needs", "disease_resistance", "infant_survival_rate",
)
_SPECIES_INTS = (
    "max_age", "gestation_time", "litter_size",
    "parental_care_duration", "min_reproduction_age",
)
_SPECIES_STRS = ("diet_type", "mating_season_start", "mating_season_end")

_BIOME_FLOATS = (
    "carrying_capacity", "base_temperature", "base_humidity", "base_precipitation",
    "min_altitude", "max_altitude", "min_temperature", "max_temperature",
    "min_humidity", "max_humidity", "regen_modifier",
)


# -- from_dict ---------------------------------------------------------------


def species_from_dict(d: Mapping[str, Any]) -> SpeciesData:
    """Build :class:`SpeciesData` from a raw record (``id``/``name`` required)."""
    m = _require_mapping(d, "species")
    kw: dict[str, Any] = {}
    kw["id"] = _req_str(m, "id", "species")
    kw["name"] = _req_str(m, "name", "species")
    for k in _SPECIES_STRS:
        _put(kw, k, _opt_str(m, k, "species"))
    for k in _SPECIES_FLOATS:
        _put(kw, k, _opt_float(m, k, "species"))
    for k in _SPECIES_INTS:
        _put(kw, k, _opt_int(m, k, "species"))
    _put(kw, "monogamous", _opt_bool(m, "monogamous", "species"))
    _put(kw, "consumes", _opt_tuplestr(m, "consumes", "species"))
    return SpeciesData(**kw)


def biome_from_dict(d: Mapping[str, Any]) -> BiomeData:
    """Build :class:`BiomeData` from a raw record (``id``/``name`` required)."""
    m = _require_mapping(d, "biome")
    kw: dict[str, Any] = {}
    kw["id"] = _req_str(m, "id", "biome")
    kw["name"] = _req_str(m, "name", "biome")
    for k in _BIOME_FLOATS:
        _put(kw, k, _opt_float(m, k, "biome"))
    _put(kw, "supported_resources", _opt_tuplestr(m, "supported_resources", "biome"))
    return BiomeData(**kw)


def plant_from_dict(d: Mapping[str, Any]) -> PlantData:
    """Build :class:`PlantData` from a raw record (``id``/``name`` required)."""
    m = _require_mapping(d, "plant")
    kw: dict[str, Any] = {}
    kw["id"] = _req_str(m, "id", "plant")
    kw["name"] = _req_str(m, "name", "plant")
    for k in ("max_biomass", "regeneration_rate", "nutritional_value", "toxicity"):
        _put(kw, k, _opt_float(m, k, "plant"))
    _put(kw, "supported_biomes", _opt_tuplestr(m, "supported_biomes", "plant"))
    _put(kw, "season_effect", _opt_season(m, "season_effect", "plant"))
    return PlantData(**kw)


def resource_from_dict(d: Mapping[str, Any]) -> ResourceData:
    """Build :class:`ResourceData` from a raw record (``id``/``name`` required)."""
    m = _require_mapping(d, "resource")
    kw: dict[str, Any] = {}
    kw["id"] = _req_str(m, "id", "resource")
    kw["name"] = _req_str(m, "name", "resource")
    for k in ("max_amount", "regeneration_rate", "nutritional_value", "toxicity"):
        _put(kw, k, _opt_float(m, k, "resource"))
    _put(kw, "season_effect", _opt_season(m, "season_effect", "resource"))
    return ResourceData(**kw)


# -- from_file ---------------------------------------------------------------


def _load_json_list(path: str | Path, where: str) -> list[Any]:
    """Read a JSON document that must be a top-level ``list`` of records."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidDataError(f"{where}: cannot read {p!s}: {exc}") from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidDataError(f"{where}: invalid JSON in {p!s}: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(doc, list):
        raise InvalidDataError(
            f"{where}: expected a JSON list of records at {p!s}, got {type(doc).__name__}"
        )
    return doc


def species_from_file(path: str | Path) -> list[SpeciesData]:
    """Load a JSON list of species records → ``list[SpeciesData]``."""
    return [species_from_dict(rec) for rec in _load_json_list(path, "species")]


def biome_from_file(path: str | Path) -> list[BiomeData]:
    """Load a JSON list of biome records → ``list[BiomeData]``."""
    return [biome_from_dict(rec) for rec in _load_json_list(path, "biome")]


def plant_from_file(path: str | Path) -> list[PlantData]:
    """Load a JSON list of plant records → ``list[PlantData]``."""
    return [plant_from_dict(rec) for rec in _load_json_list(path, "plant")]


def resource_from_file(path: str | Path) -> list[ResourceData]:
    """Load a JSON list of resource records → ``list[ResourceData]``."""
    return [resource_from_dict(rec) for rec in _load_json_list(path, "resource")]
