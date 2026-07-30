"""Tests for :mod:`population_engine.data.registry` — DataRegistry behaviour."""

from __future__ import annotations

import pytest

from population_engine.data.exceptions import DuplicateDataError, UnknownDataError
from population_engine.data.models import BiomeData, PlantData, ResourceData, SpeciesData
from population_engine.data.registry import DataRegistry


# -- successful loading -----------------------------------------------------


def test_load_then_get_returns_exact_object() -> None:
    r = DataRegistry()
    jag = SpeciesData("jaguar", "Jaguar", max_hp=90)
    r.load_species([jag])
    assert r.has_species("jaguar") is True
    assert r.species("jaguar") is jag  # exact stored object
    assert r.species("jaguar").max_hp == 90.0


def test_all_species_returned_as_tuple_in_load_order() -> None:
    r = DataRegistry()
    r.load_species([SpeciesData("a", "A"), SpeciesData("b", "B")])
    out = r.all_species()
    assert isinstance(out, tuple)
    assert [s.id for s in out] == ["a", "b"]


def test_empty_registry_lookups() -> None:
    r = DataRegistry()
    assert r.all_species() == ()
    assert r.all_biomes() == ()
    assert r.has_plant("anything") is False


# -- duplicate ids raise (atomic) --------------------------------------------


def test_duplicate_within_batch_atomic() -> None:
    r = DataRegistry()
    with pytest.raises(DuplicateDataError):
        r.load_species([SpeciesData("a", "A"), SpeciesData("a", "A2")])
    # Atomic: the rejected batch inserted nothing.
    assert r.all_species() == ()
    assert r.has_species("a") is False


def test_duplicate_across_loads_keeps_original() -> None:
    r = DataRegistry()
    r.load_species([SpeciesData("a", "A")])
    with pytest.raises(DuplicateDataError):
        r.load_species([SpeciesData("a", "A2")])
    # The original record is untouched.
    assert r.species("a").name == "A"
    assert len(r.all_species()) == 1


def test_duplicate_in_biome_batch_atomic() -> None:
    r = DataRegistry()
    with pytest.raises(DuplicateDataError):
        r.load_biomes([BiomeData("p", "P"), BiomeData("p", "P2")])
    assert r.all_biomes() == ()


# -- unknown ids raise ------------------------------------------------------


def test_unknown_id_raises_unknown_data_error() -> None:
    r = DataRegistry()
    with pytest.raises(UnknownDataError):
        r.species("nope")
    with pytest.raises(UnknownDataError):
        r.resource("nope")


# -- immutable dataclasses & unchanged snapshots -----------------------------


def test_returned_models_are_frozen() -> None:
    r = DataRegistry()
    r.load_species([SpeciesData("a", "A")])
    s = r.species("a")
    with pytest.raises(Exception):  # FrozenInstanceError
        s.max_hp = 5  # type: ignore[misc]


def test_all_species_snapshot_is_stable() -> None:
    r = DataRegistry()
    r.load_species([SpeciesData("a", "A")])
    snap = r.all_species()
    r.load_species([SpeciesData("b", "B")])
    # The earlier snapshot is unaffected by the later load (it's a new tuple).
    assert len(snap) == 1
    assert len(r.all_species()) == 2


def test_internal_dict_not_exposed() -> None:
    # No attribute lets a caller mutate the registry's contents; ``all_*`` is a
    # fresh tuple each call and the models are frozen.
    r = DataRegistry()
    r.load_species([SpeciesData("a", "A")])
    out = r.all_species()
    # The snapshot is a genuine immutable tuple: item assignment is rejected
    # with TypeError (``tuple`` has no ``append`` to begin with, but item
    # assignment is the canonical immutability check and the documented
    # expectation here).
    with pytest.raises(TypeError):
        out[0] = SpeciesData("b", "B")  # type: ignore[index,call-overload]


# -- multiple loads behave correctly ----------------------------------------


def test_multiple_loads_accumulate_in_order() -> None:
    r = DataRegistry()
    r.load_species([SpeciesData("a", "A"), SpeciesData("b", "B")])
    r.load_species([SpeciesData("c", "C")])
    assert [s.id for s in r.all_species()] == ["a", "b", "c"]
    assert r.has_species("c") is True


def test_empty_load_is_noop() -> None:
    r = DataRegistry()
    r.load_species([])
    assert r.all_species() == ()


# -- cross-kind independence ------------------------------------------------


def test_kinds_are_independent() -> None:
    r = DataRegistry()
    r.load_species([SpeciesData("wolf", "Wolf")])
    # Loading species does not populate/interfere with biomes/plants/resources.
    assert r.has_biome("wolf") is False
    with pytest.raises(UnknownDataError):
        r.biome("wolf")
    r.load_biomes([BiomeData("forest", "Forest")])
    assert r.biome("forest").id == "forest"
    assert r.has_species("forest") is False


# -- wrong type to load ----------------------------------------------------


def test_load_rejects_non_model_instances() -> None:
    r = DataRegistry()
    with pytest.raises(TypeError):
        r.load_species([{"id": "a", "name": "A"}])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        r.load_species([BiomeData("b", "B")])  # type: ignore[list-item]
    assert r.all_species() == ()  # nothing inserted


# -- plants / resources round-trip (incl. season effect) --------------------


def test_plant_and_resource_round_trip() -> None:
    r = DataRegistry()
    water = ResourceData("water", "Water", season_effect=(("rainy", 1.5), ("dry", 0.5)))
    r.load_resources([water])
    got = r.resource("water")
    assert got is water
    assert got.season_effect == (("rainy", 1.5), ("dry", 0.5))

    grass = PlantData("grass", "Grass", supported_biomes=("forest",))
    r.load_plants([grass])
    assert r.plant("grass").supported_biomes == ("forest",)
    assert r.has_plant("grass") is True
