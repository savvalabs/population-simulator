"""Tests for :mod:`population_engine.data.loader` — dict/file → models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from population_engine.data.exceptions import InvalidDataError
from population_engine.data.loader import (
    biome_from_dict,
    biome_from_file,
    plant_from_dict,
    plant_from_file,
    resource_from_dict,
    species_from_dict,
    species_from_file,
)


# -- species_from_dict ------------------------------------------------------


def test_species_from_dict_minimal_defaults() -> None:
    s = species_from_dict({"id": "jaguar", "name": "Jaguar"})
    assert s.id == "jaguar" and s.name == "Jaguar"
    assert s.max_hp == 100.0 and s.max_age == 1000  # defaults applied
    assert s.consumes == ()


def test_species_from_dict_overrides_and_numeric_coercion() -> None:
    s = species_from_dict(
        {
            "id": "wolf", "name": "Wolf", "diet_type": "carnivore",
            "max_hp": 80, "max_age": 1500, "speed": 1.5, "monogamous": True,
            "consumes": ["deer", "rabbit"],
        }
    )
    assert s.diet_type == "carnivore"
    assert s.max_hp == 80.0 and isinstance(s.max_hp, float)
    assert s.max_age == 1500 and isinstance(s.max_age, int)
    assert s.monogamous is True
    assert s.consumes == ("deer", "rabbit")
    assert isinstance(s.consumes, tuple)


def test_species_from_dict_requires_id_and_name() -> None:
    with pytest.raises(InvalidDataError):
        species_from_dict({"name": "Wolf"})
    with pytest.raises(InvalidDataError):
        species_from_dict({"id": "wolf"})
    with pytest.raises(InvalidDataError):
        species_from_dict({"id": "", "name": "Wolf"})


def test_species_from_dict_rejects_wrong_types() -> None:
    with pytest.raises(InvalidDataError):
        species_from_dict({"id": "x", "name": "X", "max_hp": "huge"})  # str not num
    with pytest.raises(InvalidDataError):
        species_from_dict({"id": "x", "name": "X", "max_age": 12.5})  # float not int
    with pytest.raises(InvalidDataError):
        species_from_dict({"id": "x", "name": "X", "monogamous": "yes"})  # str not bool
    # Non-mapping record:
    with pytest.raises(InvalidDataError):
        species_from_dict("not a dict")  # type: ignore[arg-type]


# -- biome_from_dict --------------------------------------------------------


def test_biome_from_dict() -> None:
    b = biome_from_dict({"id": "paramo", "name": "Páramo", "supported_resources": ["grass", "water"]})
    assert b.carrying_capacity == 100.0  # default applied
    assert b.supported_resources == ("grass", "water")
    with pytest.raises(InvalidDataError):
        biome_from_dict({"id": "x"})  # missing name


# -- plant / resource season_effect ----------------------------------------


def test_plant_season_effect_from_dict_is_sorted() -> None:
    # Author in rainy-then-dry order; loader sorts by season label.
    p = plant_from_dict(
        {"id": "grass", "name": "Grass", "season_effect": {"rainy": 1.5, "dry": 1.0}}
    )
    assert p.season_effect == (("dry", 1.0), ("rainy", 1.5))


def test_plant_season_effect_from_list_is_sorted() -> None:
    p = plant_from_dict(
        {"id": "grass", "name": "Grass", "season_effect": [["rainy", 1.5], ["dry", 1.0]]}
    )
    assert p.season_effect == (("dry", 1.0), ("rainy", 1.5))


def test_resource_from_dict() -> None:
    r = resource_from_dict({"id": "water", "name": "Water", "season_effect": [["dry", 0.5]]})
    assert r.max_amount == 100.0
    assert r.season_effect == (("dry", 0.5),)
    with pytest.raises(InvalidDataError):
        resource_from_dict({"id": "x", "name": "X", "season_effect": [1, 2]})  # not pairs


# -- from_file --------------------------------------------------------------


def _write(tmp_path: Path, name: str, obj: object) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_species_from_file(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "species.json",
        [
            {"id": "jaguar", "name": "Jaguar", "max_hp": 90},
            {"id": "puma", "name": "Puma"},
        ],
    )
    out = species_from_file(p)
    assert len(out) == 2
    assert [s.id for s in out] == ["jaguar", "puma"]
    assert out[0].max_hp == 90.0 and out[1].max_hp == 100.0  # override + default


def test_biome_from_file(tmp_path: Path) -> None:
    p = _write(tmp_path, "biomes.json", [{"id": "paramo", "name": "Páramo"}])
    out = biome_from_file(p)
    assert len(out) == 1 and out[0].id == "paramo"


def test_from_file_rejects_non_list(tmp_path: Path) -> None:
    p = _write(tmp_path, "species.json", {"id": "jaguar", "name": "Jaguar"})
    with pytest.raises(InvalidDataError):
        species_from_file(p)


def test_from_file_rejects_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidDataError):
        species_from_file(p)


def test_from_file_rejects_record_without_id(tmp_path: Path) -> None:
    p = _write(tmp_path, "species.json", [{"name": "Jaguar"}])
    with pytest.raises(InvalidDataError):
        species_from_file(p)


def test_from_file_missing_path(tmp_path: Path) -> None:
    with pytest.raises(InvalidDataError):
        species_from_file(tmp_path / "nope.json")
