"""S1 gate test — the bundled authored sources load and look up by id.

The S1 gate (CORE_DESIGN §9): *load bundled sources, by-id lookups work,
validation fails closed.* The model/loader/registry units already exercise
``validation fails closed`` on synthetic records; this module proves the
shipped ``sources/*.json`` actually round-trip through :func:`load_default_registry`
into a usable :class:`DataRegistry`, and that the authored content is internally
self-consistent (no dangling cross-id references).
"""

from __future__ import annotations

import pytest

from population_engine.data import load_default_registry
from population_engine.data.exceptions import UnknownDataError


# -- the gate: bundled sources load, lookups work, fail closed ----------------


def test_bundled_sources_load_every_kind() -> None:
    reg = load_default_registry()
    # All four kinds non-empty — the bundle actually ships content.
    assert len(reg.all_biomes()) > 0
    assert len(reg.all_resources()) > 0
    assert len(reg.all_plants()) > 0
    assert len(reg.all_species()) > 0


def test_bundled_by_id_lookup_and_presence() -> None:
    reg = load_default_registry()
    # By-id lookups (the gate) return the authored template for known ids.
    assert reg.has_species("jaguar") and reg.species("jaguar").id == "jaguar"
    assert reg.has_biome("paramo") and reg.biome("paramo").name == "Páramo"
    assert reg.has_plant("grass") and reg.plant("grass").id == "grass"
    assert reg.has_resource("water") and reg.resource("water").id == "water"


def test_bundled_unknown_id_fails_closed() -> None:
    # Validation fails closed at lookup: an unknown id raises, not returns None.
    reg = load_default_registry()
    with pytest.raises(UnknownDataError):
        reg.species("dodo")
    with pytest.raises(UnknownDataError):
        reg.biome("tundra")
    assert reg.has_species("dodo") is False
    assert reg.has_resource("unicorns") is False


# -- authored content is internally referentially consistent -------------------


def test_bundled_consumes_reference_known_ids() -> None:
    reg = load_default_registry()
    # A species' ``consumes`` may point at other species, plants, or resources —
    # all of which are registry ids. Nothing should dangle.
    consumable = (
        {s.id for s in reg.all_species()}
        | {p.id for p in reg.all_plants()}
        | {r.id for r in reg.all_resources()}
    )
    for s in reg.all_species():
        for item in s.consumes:
            assert item in consumable, f"{s.id!r}.consumes -> unknown id {item!r}"


def test_bundled_plants_reference_known_biomes() -> None:
    reg = load_default_registry()
    for p in reg.all_plants():
        for biome_id in p.supported_biomes:
            assert reg.has_biome(biome_id), (
                f"{p.id!r}.supported_biomes -> unknown biome {biome_id!r}"
            )


def test_bundled_biomes_reference_known_resources() -> None:
    reg = load_default_registry()
    for b in reg.all_biomes():
        for resource_id in b.supported_resources:
            assert reg.has_resource(resource_id), (
                f"{b.id!r}.supported_resources -> unknown resource {resource_id!r}"
            )


# -- the bundle exercises the full SpeciesData schema -------------------------


def test_bundled_species_exercises_full_schema() -> None:
    reg = load_default_registry()
    # Diet types: the bundle covers every kind the schema anticipates.
    diets = {s.diet_type for s in reg.all_species()}
    assert {"herbivore", "carnivore", "omnivore", "scavenger"} <= diets

    # Motion: at least one flyer and one swimmer (flight_speed / swim_speed > 0).
    assert any(s.flight_speed > 0.0 for s in reg.all_species())   # condor
    assert any(s.swim_speed > 0.0 for s in reg.all_species())     # tapir / jaguar

    # Reproduction: both monogamy values and a bounded mating season appear.
    assert any(s.monogamous is True for s in reg.all_species())   # condor
    assert any(s.monogamous is False for s in reg.all_species())
    assert any(s.mating_season_start != "" for s in reg.all_species())  # tapir

    # The numeric groups are populated (vitals / metabolism / tolerances are
    # overridden away from defaults somewhere in the bundle).
    assert any(s.max_hp != 100.0 for s in reg.all_species())
    assert any(s.max_age != 1000 for s in reg.all_species())
    assert any(s.metabolic_rate != 1.0 for s in reg.all_species())
    assert any(s.hunt_skill > 0.0 for s in reg.all_species())      # carnivores


def test_bundled_season_effects_are_sorted_floats() -> None:
    # The loader sorts ``season_effect`` by season label for determinism; the
    # bundled content must round-trip that contract.
    reg = load_default_registry()
    water = reg.resource("water")
    assert water.season_effect == (("dry", 0.4), ("rainy", 1.5))
    assert all(isinstance(m, float) for _, m in water.season_effect)


def test_bundled_load_is_deterministic() -> None:
    # Two loads produce the same id order and stable season-effect bytes.
    a = load_default_registry()
    b = load_default_registry()
    assert [s.id for s in a.all_species()] == [s.id for s in b.all_species()]
    assert a.resource("water").season_effect == b.resource("water").season_effect
