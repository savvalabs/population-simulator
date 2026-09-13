"""Tests for ExposureSystem, EnvironmentPressureSystem and DeathSystem.

Covers the §3.1 "hinge" split: ExposureSystem is the only world-coupled
entity system; EnvironmentPressureSystem is world-free and consumes
CellExposure; DeathSystem reaps energy-depleted entities.
"""

from __future__ import annotations

from population_engine.ecs.components import (
    CellExposure,
    EnergyComponent,
    PhenotypeComponent,
    Position,
)
from population_engine.ecs.events import EventBus
from population_engine.ecs.registry import Registry
from population_engine.ecs.scheduler import SystemContext
from population_engine.systems.death import DeathSystem
from population_engine.systems.environment_exposure import ExposureSystem
from population_engine.systems.environment_pressure import (
    COMFORT_TEMPERATURE,
    EnvironmentPressureSystem,
)
from population_engine.world.coords import CellCoord, ChunkCoord
from population_engine.world.world import World


def _world(chunk_size: int = 4) -> World:
    return World(width_chunks=1, height_chunks=1, chunk_size=chunk_size)


def _ctx(registry: Registry, world: World | None = None) -> SystemContext:
    return SystemContext(registry=registry, events=EventBus(), world=world)


def _set_climate(world: World, temperature: float) -> None:
    chunk = world.chunk(ChunkCoord(0, 0))
    chunk.field("temperature").interior[...] = temperature
    chunk.field("humidity").interior[...] = 0.0
    chunk.field("precipitation").interior[...] = 0.0


class TestExposureSystem:
    def test_snapshots_cell_temperature(self):
        registry = Registry()
        world = _world()
        _set_climate(world, -12.5)
        entity = registry.create_entity(Position(x=1, y=2), CellExposure())
        ExposureSystem().update(_ctx(registry, world))
        exposure = registry.get_component(entity, CellExposure)
        assert exposure.temperature == -12.5
        assert exposure.humidity == 0.0
        assert exposure.precipitation == 0.0

    def test_reads_exact_cell(self):
        registry = Registry()
        world = _world()
        chunk = world.chunk(ChunkCoord(0, 0))
        chunk.field("temperature").interior[...] = 15.0
        chunk.field("temperature").interior[2, 3] = -40.0
        cold = registry.create_entity(Position(x=3, y=2), CellExposure())
        warm = registry.create_entity(Position(x=0, y=0), CellExposure())
        ExposureSystem().update(_ctx(registry, world))
        assert registry.get_component(cold, CellExposure).temperature == -40.0
        assert registry.get_component(warm, CellExposure).temperature == 15.0

    def test_updates_existing_component_each_tick(self):
        registry = Registry()
        world = _world()
        entity = registry.create_entity(Position(x=0, y=0), CellExposure())
        _set_climate(world, 5.0)
        ExposureSystem().update(_ctx(registry, world))
        assert registry.get_component(entity, CellExposure).temperature == 5.0
        _set_climate(world, -7.0)
        ExposureSystem().update(_ctx(registry, world))
        assert registry.get_component(entity, CellExposure).temperature == -7.0

    def test_entity_without_exposure_gets_one(self):
        registry = Registry()
        world = _world()
        _set_climate(world, -3.0)
        entity = registry.create_entity(Position(x=0, y=0))
        ExposureSystem().update(_ctx(registry, world))
        assert registry.get_component(entity, CellExposure).temperature == -3.0

    def test_entities_without_position_ignored(self):
        registry = Registry()
        world = _world()
        entity = registry.create_entity(EnergyComponent())
        ExposureSystem().update(_ctx(registry, world))
        assert not registry.has_component(entity, CellExposure)

    def test_no_world_is_noop(self):
        registry = Registry()
        entity = registry.create_entity(Position(), CellExposure())
        ExposureSystem().update(_ctx(registry, None))
        assert (
            registry.get_component(entity, CellExposure).temperature == 0.0
        )


class TestEnvironmentPressureSystem:
    def test_cold_entity_loses_energy(self):
        # cold_resistance = 0 -> tolerates down to 20 °C; exposure -5 °C ->
        # penalty = int(20.0 - (-5.0)) = 25.
        registry = Registry()
        entity = registry.create_entity(
            CellExposure(temperature=-5.0),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=100),
        )
        EnvironmentPressureSystem().update(_ctx(registry))
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            == 75
        )

    def test_warm_cell_no_penalty(self):
        registry = Registry()
        entity = registry.create_entity(
            CellExposure(temperature=25.0),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=100),
        )
        EnvironmentPressureSystem().update(_ctx(registry))
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            == 100
        )

    def test_cold_resistance_covers_temperature(self):
        # resistance 30 -> tolerates down to -10 °C; exposure -5 °C is fine.
        registry = Registry()
        entity = registry.create_entity(
            CellExposure(temperature=-5.0),
            PhenotypeComponent(cold_resistance=30.0),
            EnergyComponent(current_energy=100),
        )
        EnvironmentPressureSystem().update(_ctx(registry))
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            == 100
        )

    def test_penalty_is_int_truncated(self):
        registry = Registry()
        entity = registry.create_entity(
            CellExposure(temperature=COMFORT_TEMPERATURE - 5.5),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=10),
        )
        EnvironmentPressureSystem().update(_ctx(registry))
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            == 5
        )

    def test_entities_without_full_triple_are_ignored(self):
        registry = Registry()
        no_energy = registry.create_entity(
            CellExposure(temperature=-50.0), PhenotypeComponent()
        )
        no_phenotype = registry.create_entity(
            CellExposure(temperature=-50.0), EnergyComponent()
        )
        EnvironmentPressureSystem().update(_ctx(registry))
        assert registry.has_component(no_energy, CellExposure)
        assert (
            registry.get_component(no_phenotype, EnergyComponent).current_energy
            == 100
        )

    def test_energy_can_go_negative_for_death_system(self):
        registry = Registry()
        entity = registry.create_entity(
            CellExposure(temperature=-90.0),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=10),
        )
        EnvironmentPressureSystem().update(_ctx(registry))
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            <= 0
        )

    def test_no_world_needed(self):
        # Regression for the hinge refactor: the system must NOT read
        # ctx.world at all; a None world must still apply penalties.
        registry = Registry()
        entity = registry.create_entity(
            CellExposure(temperature=-5.0),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=100),
        )
        EnvironmentPressureSystem().update(_ctx(registry, None))
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            == 75
        )


class TestDeathSystem:
    def test_zero_energy_entity_is_destroyed(self):
        registry = Registry()
        entity = registry.create_entity(EnergyComponent(current_energy=0))
        DeathSystem().update(_ctx(registry))
        assert entity not in set(registry.alive_entities())
        assert len(registry) == 0

    def test_negative_energy_entity_is_destroyed(self):
        registry = Registry()
        registry.create_entity(EnergyComponent(current_energy=-7))
        DeathSystem().update(_ctx(registry))
        assert len(registry) == 0

    def test_alive_entities_survive(self):
        registry = Registry()
        survivor = registry.create_entity(EnergyComponent(current_energy=1))
        registry.create_entity(EnergyComponent(current_energy=0))
        DeathSystem().update(_ctx(registry))
        assert len(registry) == 1
        assert registry.has_component(survivor, EnergyComponent)
        assert (
            registry.get_component(survivor, EnergyComponent).current_energy
            == 1
        )

    def test_entities_without_energy_untouched(self):
        registry = Registry()
        plain = registry.create_entity(Position(x=3, y=3))
        DeathSystem().update(_ctx(registry))
        assert registry.has_component(plain, Position)

    def test_destroys_all_components_of_dead_entity(self):
        registry = Registry()
        entity = registry.create_entity(
            Position(x=1, y=2),
            PhenotypeComponent(),
            EnergyComponent(current_energy=0),
        )
        DeathSystem().update(_ctx(registry))
        assert entity not in set(registry.alive_entities())
        assert len(registry) == 0

    def test_noop_when_nobody_dead(self):
        registry = Registry()
        registry.create_entity(EnergyComponent(current_energy=100))
        registry.create_entity(EnergyComponent(current_energy=55))
        DeathSystem().update(_ctx(registry))
        assert len(registry) == 2


class TestPipelineIntegration:
    """End-to-end: World -> Exposure -> Pressure -> Death."""

    def test_hinge_pipeline_freeze_then_reap(self):
        registry = Registry()
        world = _world()
        _set_climate(world, -40.0)
        doomed = registry.create_entity(
            Position(x=0, y=0),
            CellExposure(),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=50),
        )
        adapted = registry.create_entity(
            Position(x=1, y=1),
            CellExposure(),
            PhenotypeComponent(cold_resistance=100.0),
            EnergyComponent(current_energy=50),
        )
        ctx = _ctx(registry, world)
        ExposureSystem().update(ctx)
        assert (
            registry.get_component(doomed, CellExposure).temperature == -40.0
        )
        EnvironmentPressureSystem().update(ctx)
        assert (
            registry.get_component(doomed, EnergyComponent).current_energy
            <= 0
        )
        assert (
            registry.get_component(adapted, EnergyComponent).current_energy
            == 50
        )
        DeathSystem().update(ctx)
        assert len(registry) == 1
        assert registry.has_component(adapted, EnergyComponent)

    def test_exposure_decouples_pressure_from_world(self):
        # If the world changes between exposure and pressure, pressure must
        # see the SNAPSHOT, not the live world.
        registry = Registry()
        world = _world()
        _set_climate(world, -5.0)
        entity = registry.create_entity(
            Position(x=0, y=0),
            CellExposure(),
            PhenotypeComponent(cold_resistance=0.0),
            EnergyComponent(current_energy=100),
        )
        ExposureSystem().update(_ctx(registry, world))
        _set_climate(world, 30.0)  # world warms AFTER the snapshot
        EnvironmentPressureSystem().update(_ctx(registry, world))
        # Penalty from the -5 °C snapshot: 100 - 25 = 75.
        assert (
            registry.get_component(entity, EnergyComponent).current_energy
            == 75
        )

    def test_cellcoord_used_for_lookup(self):
        # Smoke: CellCoord import surface used by the systems is coherent.
        coord = CellCoord(3, 2)
        assert (coord.x, coord.y) == (3, 2)
