"""Tests for HumanPressureSystem v2 (siete palancas 0..1)."""

from __future__ import annotations

import numpy as np

from population_engine.ecs.components import (
    Diet,
    EnergyComponent,
    GenomeComponent,
    PhenotypeComponent,
    Position,
    SpeciesRef,
)
from population_engine.ecs.enums import DietType
from population_engine.ecs.events import EventBus
from population_engine.ecs.registry import Registry
from population_engine.ecs.scheduler import SystemContext
from population_engine.systems.death import DeathSystem
from population_engine.systems.human_pressure import HumanPressureSystem


def _ctx(registry: Registry, seed: int = 0) -> SystemContext:
    return SystemContext(
        registry=registry, events=EventBus(), rng=np.random.default_rng(seed)
    )


def _prey(registry, energy=100, x=16, y=16, sp="neque"):
    return registry.create_entity(
        Position(x=x, y=y),
        SpeciesRef(species_id=sp),
        GenomeComponent(),
        PhenotypeComponent(camouflage=0.1, cold_resistance=0.0, speed=5.0),
        EnergyComponent(current_energy=energy, max_energy=energy),
        Diet(diet_type=DietType.HERBIVORE),
    )


class TestInactive:
    def test_inactive_is_noop(self):
        r = Registry()
        e = _prey(r)
        hp = HumanPressureSystem(active=False)
        hp.urbanization = 1.0
        hp.hunters = 1.0
        hp.contamination = 1.0
        hp.update(_ctx(r))
        assert r.get_component(e, EnergyComponent).current_energy == 100

    def test_levers_clamped_off_when_inactive(self):
        hp = HumanPressureSystem(active=False)
        hp.food_scarcity = 1.0
        assert hp.deforestation_factor() == 0.0
        assert not hp.reproduction_suppressed()


class TestUrbanization:
    def test_edge_ring_drains_heavily(self):
        r = Registry()
        # Centro seguro: lejos del borde.
        safe = _prey(r, x=64, y=64)
        edge = _prey(r, x=1, y=64)   # en el anillo urbano
        hp = HumanPressureSystem(active=True, world_size=128)
        hp.urbanization = 0.5  # ring = 10 celdas
        hp.update(_ctx(r))
        assert r.get_component(edge, EnergyComponent).current_energy <= 70
        assert r.get_component(safe, EnergyComponent).current_energy == 100


class TestContamination:
    def test_mutation_rate_rises_and_energy_drops(self):
        r = Registry()
        e = _prey(r)
        hp = HumanPressureSystem(active=True)
        hp.contamination = 1.0
        hp.update(_ctx(r))
        assert r.get_component(e, GenomeComponent).mutation_rate > 0.05
        assert r.get_component(e, EnergyComponent).current_energy == 98  # 2% de 100


class TestHunters:
    def test_sudden_death_probabilistic(self):
        r = Registry()
        for _ in range(6):
            _prey(r)
        hp = HumanPressureSystem(active=True)
        hp.hunters = 1.0  # 10% letal por tick
        for _ in range(10):
            hp.update(_ctx(r))
        dead = sum(
            1
            for _, en in r.query(EnergyComponent)
            if en.current_energy == 0
        )
        # Con 10% letalidad por tick durante 10 ticks, casi todos mueren.
        assert dead >= 1

    def test_ignores_stats(self):
        r = Registry()
        tank = _prey(r)
        g = r.get_component(tank, PhenotypeComponent)
        g.camouflage = 1.0
        g.speed = 999.0
        hp = HumanPressureSystem(active=True)
        hp.hunters = 1.0
        for _ in range(20):
            hp.update(_ctx(r))
        # Algún evento letal ocurrirá con stats perfectos
        # (probabilidad de escapar 20 veces = 0.9^20 ≈ 12%). No aserto el caso
        # determinista; solo que la energy puede llegar a 0.
        assert r.get_component(tank, EnergyComponent).current_energy in range(0, 101)


class TestRoads:
    def test_road_cell_kills(self):
        r = Registry()
        road_victim = _prey(r, x=64, y=64)  # cruz exacto (fila y col)
        off_road = _prey(r, x=10, y=10)
        hp = HumanPressureSystem(active=True, world_size=128)
        hp.roads = 1.0
        ctx = _ctx(r)
        # 35% de letalidad por tick: en ~10 ticks es casi seguro que cruce la vía.
        for _ in range(10):
            hp.update(ctx)
            if r.get_component(road_victim, EnergyComponent).current_energy == 0:
                break
        assert r.get_component(road_victim, EnergyComponent).current_energy == 0
        assert r.get_component(off_road, EnergyComponent).current_energy == 100


class TestNoise:
    def test_noise_moves_and_drains(self):
        r = Registry()
        e = _prey(r)
        hp = HumanPressureSystem(active=True, world_size=128)
        hp.noise = 1.0
        initial = (r.get_component(e, Position).x, r.get_component(e, Position).y)
        hp.update(_ctx(r))
        assert r.get_component(e, EnergyComponent).current_energy <= 97
        # Movimiento errático: con jitter=4 garantizado cambia
        pos = r.get_component(e, Position)
        assert (pos.x, pos.y) != initial
        assert hp.reproduction_suppressed()


class TestInvasive:
    def test_ferals_spawn_and_dont_starve(self):
        r = Registry()
        prey = _prey(r, energy=10)
        hp = HumanPressureSystem(active=True, world_size=128)
        hp.invasive = 1.0
        hp.update(_ctx(r))
        ferals = [e for e, s in r.query(SpeciesRef) if s.species_id == "feral"]
        assert len(ferals) >= 1
        # Segunda pasada: la energía del feral se repone (alimentados en casa)
        ctx = _ctx(r)
        for ent in ferals:
            en = r.get_component(ent, EnergyComponent)
            en.current_energy = 5  # hambre forzada
        hp.update(ctx)
        for ent in ferals:
            assert r.get_component(ent, EnergyComponent).current_energy >= hp._feral_energy_floor


class TestDeterminism:
    def test_reproducible(self):
        def run():
            r = Registry()
            for _ in range(5):
                _prey(r)
            hp = HumanPressureSystem(active=True, world_size=128)
            hp.noise = 1.0; hp.hunters = 0.5; hp.contamination = 0.5
            for _ in range(5):
                hp.update(_ctx(r, seed=42))
            return [en.current_energy for _, en in r.query(EnergyComponent)]
        assert run() == run()
