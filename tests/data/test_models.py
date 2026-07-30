"""Tests for :mod:`population_engine.data.models` — frozen templates + validation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from population_engine.data.exceptions import InvalidDataError
from population_engine.data.models import (
    BiomeData,
    PlantData,
    ResourceData,
    SpeciesData,
)


# -- SpeciesData -------------------------------------------------------------


def test_species_defaults_well_formed() -> None:
    s = SpeciesData("jaguar", "Jaguar")
    assert s.id == "jaguar" and s.name == "Jaguar"
    assert s.diet_type == "herbivore"
    assert s.consumes == ()
    assert s.max_hp == 100.0 and s.max_age == 1000
    assert s.monogamous is False


def test_species_is_frozen() -> None:
    s = SpeciesData("jaguar", "Jaguar")
    with pytest.raises(FrozenInstanceError):
        s.max_hp = 999  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        s.id = "puma"  # type: ignore[misc]


def test_species_is_hashable() -> None:
    # All fields are hashable (str/int/float/tuple-of-str/tuple-of-pairs/bool).
    a = SpeciesData("jaguar", "Jaguar", consumes=("deer", "capybara"))
    b = SpeciesData("jaguar", "Jaguar", consumes=("deer", "capybara"))
    assert a == b and hash(a) == hash(b)
    assert len({a, b, SpeciesData("puma", "Puma")}) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "", "name": "x"},
        {"id": "x", "name": ""},
        {"id": 5, "name": "x"},  # type: ignore[dict-item]
    ],
)
def test_species_requires_nonempty_id_name(kwargs: dict) -> None:
    with pytest.raises(InvalidDataError):
        SpeciesData(**kwargs)  # type: ignore[arg-type]


def test_species_rejects_negative_numerics() -> None:
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", max_hp=-1.0)
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", max_age=-5)
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", territory_size=-0.1)
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", reproduction_rate=-1.0)


def test_species_rejects_reversed_tolerance_ranges() -> None:
    with pytest.raises(InvalidDataError):
        SpeciesData(
            "x", "X",
            temperature_tolerance_min=50.0,
            temperature_tolerance_max=10.0,
        )
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", humidity_tolerance_min=0.9, humidity_tolerance_max=0.1)


def test_species_rejects_bool_as_numeric() -> None:
    # bool is a subclass of int; True/False must not masquerade as a vitals cap.
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", max_hp=True)  # type: ignore[arg-type]
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", monogamous=1)  # type: ignore[arg-type]


def test_species_consumes_coerces_list_and_validates_strings() -> None:
    s = SpeciesData("x", "X", consumes=["deer", "capybara"])
    assert s.consumes == ("deer", "capybara")
    assert isinstance(s.consumes, tuple)
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", consumes=("deer", ""))  # empty id
    with pytest.raises(InvalidDataError):
        SpeciesData("x", "X", consumes="deer")  # a str, not a sequence


# -- BiomeData --------------------------------------------------------------


def test_biome_defaults_well_formed() -> None:
    b = BiomeData("paramo", "Páramo")
    assert b.carrying_capacity == 100.0
    assert b.base_humidity == 0.5
    assert b.supported_resources == ()


def test_biome_rejects_bad_ranges_and_humidity() -> None:
    with pytest.raises(InvalidDataError):
        BiomeData("x", "X", carrying_capacity=-1.0)
    with pytest.raises(InvalidDataError):
        BiomeData("x", "X", base_humidity=1.5)
    with pytest.raises(InvalidDataError):
        BiomeData("x", "X", min_altitude=3000.0, max_altitude=1000.0)
    with pytest.raises(InvalidDataError):
        BiomeData("x", "X", regen_modifier=-0.5)


def test_biome_supported_resources_coerces() -> None:
    b = BiomeData("x", "X", supported_resources=["grass", "water"])
    assert b.supported_resources == ("grass", "water")
    assert isinstance(b.supported_resources, tuple)


# -- PlantData / ResourceData ----------------------------------------------


def test_plant_defaults_and_validation() -> None:
    p = PlantData("grass", "Grass")
    assert p.max_biomass == 100.0 and p.regeneration_rate == 0.1
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", max_biomass=-1.0)
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", toxicity=-0.1)


def test_season_effect_validated_and_floats_coerced() -> None:
    # Accept ints; store floats; preserve order (insertion order here; loader
    # sorts for determinism — the model keeps what it's given, validated).
    p = PlantData("x", "X", season_effect=(("dry", 1), ("rainy", 1.5)))
    assert p.season_effect == (("dry", 1.0), ("rainy", 1.5))
    assert all(isinstance(m, float) for _, m in p.season_effect)


def test_season_effect_rejects_malformed() -> None:
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", season_effect=(("dry",),))  # wrong arity
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", season_effect=({"dry": 1.0}))  # dict, wrong shape
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", season_effect=(("dry", -0.5),))  # negative multiplier
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", season_effect=(("", 1.0),))  # empty season label
    with pytest.raises(InvalidDataError):
        PlantData("x", "X", season_effect="dry")  # a str


def test_resource_data_defaults_and_validation() -> None:
    r = ResourceData("water", "Water")
    assert r.max_amount == 100.0 and r.nutritional_value == 0.0
    with pytest.raises(InvalidDataError):
        ResourceData("x", "X", max_amount=-1.0)
    with pytest.raises(InvalidDataError):
        ResourceData("x", "X", regeneration_rate=-0.1)
