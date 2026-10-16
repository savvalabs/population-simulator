"""Tests for ResourceSystem + ForagingSystem + PredatorSystem (trophic chain)."""

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
from population_engine.systems.predators import (
    EAT_AMOUNT,
    HUNT_ENERGY_GAIN,
    ForagingSystem,
    PredatorSystem,
    STARVE_LOSS,
)
from population_engine.systems.resources import MAX_BIOMASS, ResourceSystem
from population_engine.world.coords import ChunkCoord
from population_engine.world.world import World


def _world(chunk_size: int = 4) -> World:
    return World(width_chunks=1, height_chunks=1, chunk_size=chunk_size)


def _ctx(registry: Registry, world: World | None = None, seed: int = 0) -> SystemContext:
    return SystemContext(
        registry=registry, events=EventBus(), world=world,
        rng=np.random.default_rng(seed),
    )


def _set_climate(world: World, temperature: float, humidity: float) -> None:
    chunk = world.chunk(ChunkCoord(0, 0))
    chunk.field("temperature").interior[...] = temperature
    chunk.field("humidity").interior[...] = humidity


def _set_biomass(world: World, value: float) -> None:
    chunk = world.chunk(ChunkCoord(0, 0))
    chunk.field("biomass").interior[...] = value


def _spawn_neque(registry, x=1, y=1, energy=50, speed=4.0):
    return registry.create_entity(
        Position(x=x, y=y),
        SpeciesRef(species_id="neque"),
        GenomeComponent(),
        PhenotypeComponent(camouflage=0.1, cold_resistance=0.0, speed=speed),
        EnergyComponent(current_energy=energy, max_energy=100),
        Diet(diet_type=DietType.HERBIVORE),
    )


def _spawn_tigrillo(registry, x=1, y=1, energy=50, speed=8.0):
    return registry.create_entity(
        Position(x=x, y=y),
        SpeciesRef(species_id="tigrillo"),
        GenomeComponent(),
        PhenotypeComponent(camouflage=0.4, cold_resistance=0.0, speed=speed),
        EnergyComponent(current_energy=energy, max_energy=150),
        Diet(diet_type=DietType.CARNIVORE),
    )


def _spawn_aguila(registry, x=1, y=1, energy=50):
    return registry.create_entity(
        Position(x=x, y=y),
        SpeciesRef(species_id="aguila"),
        GenomeComponent(),
        PhenotypeComponent(camouflage=0.5, cold_resistance=0.0, speed=8.0),
        EnergyComponent(current_energy=energy, max_energy=120),
        Diet(diet_type=DietType.CARNIVORE),
    )


class TestResourceSystem:
    def test_biomass_grows_with_climate(self):
        r = Registry()
        w = _world()
        _set_biomass(w, 0.0)
        _set_climate(w, temperature=20.0, humidity=1.0)  # óptimo
        ResourceSystem().update(_ctx(r, w))
        assert w.chunk(ChunkCoord(0, 0)).field("biomass").interior[0, 0] > 0

    def test_biomass_capped(self):
        r = Registry()
        w = _world()
        _set_biomass(w, MAX_BIOMASS - 0.5)
        _set_climate(w, temperature=28.0, humidity=1.0)
        ResourceSystem().update(_ctx(r, w))
        assert (
            w.chunk(ChunkCoord(0, 0)).field("biomass").interior[0, 0]
            == MAX_BIOMASS
        )

    def test_deforestation_kills_growth(self):
        r = Registry()
        w = _world()
        _set_biomass(w, 10.0)
        _set_climate(w, temperature=20.0, humidity=1.0)
        ResourceSystem(deforestation_getter=lambda: 1.0).update(_ctx(r, w))
        # Sin regeneración (tala total): la biomasa no crece.
        assert (
            w.chunk(ChunkCoord(0, 0)).field("biomass").interior[0, 0] == 10.0
        )


class TestForagingSystem:
    def test_herbivore_eats_and_gains_energy(self):
        r = Registry()
        w = _world()
        _set_biomass(w, 50.0)
        e = _spawn_neque(r, energy=50)
        ForagingSystem().update(_ctx(r, w))
        en = r.get_component(e, EnergyComponent)
        assert en.current_energy == 50 + int(EAT_AMOUNT)
        assert w.chunk(ChunkCoord(0, 0)).field("biomass").interior[1, 1] == 30.0

    def test_herbivore_starves_on_empty_cell(self):
        r = Registry()
        w = _world()
        _set_biomass(w, 0.0)
        e = _spawn_neque(r, energy=50)
        ForagingSystem().update(_ctx(r, w))
        assert r.get_component(e, EnergyComponent).current_energy == 50 - STARVE_LOSS

    def test_energy_never_exceeds_max(self):
        r = Registry()
        w = _world()
        _set_biomass(w, 5.0)   # pocos restos -> come 5 - 8 pierde
        e = _spawn_neque(r, energy=98)   # casi lleno: NO debe pasar de 100
        ForagingSystem().update(_ctx(r, w))
        assert r.get_component(e, EnergyComponent).current_energy <= 100

    def test_herbivore_moves_when_starving(self):
        r = Registry()
        w = _world()
        _set_biomass(w, 0.0)
        e = _spawn_neque(r, energy=50, speed=16.0)  # 16/4 = 4 celdas
        ForagingSystem().update(_ctx(r, w, seed=1))
        pos = r.get_component(e, Position)
        # Puede moverse 0..4 por eje; con jitter, al menos una coord cambia.
        assert (pos.x, pos.y) != (1, 1)


class TestPredatorSystem:
    def test_tigrillo_outspeeds_neque(self):
        r = Registry()
        w = _world()
        prey = _spawn_neque(r, energy=80, speed=4.0)
        pred = _spawn_tigrillo(r, energy=50, speed=10.0)  # 10 >= 4*1.2
        PredatorSystem().update(_ctx(r, w))
        assert r.get_component(prey, EnergyComponent).current_energy == 0
        assert r.get_component(pred, EnergyComponent).current_energy == 50 + HUNT_ENERGY_GAIN

    def test_tigrillo_fails_if_slower(self):
        r = Registry()
        w = _world()
        prey = _spawn_neque(r, speed=20.0)  # 20*1.2=24 > pred speed 10
        pred = _spawn_tigrillo(r, energy=50, speed=10.0)
        PredatorSystem().update(_ctx(r, w))
        assert r.get_component(prey, EnergyComponent).current_energy > 0
        assert r.get_component(pred, EnergyComponent).current_energy == 50

    def test_aguila_catches_despite_speed(self):
        r = Registry()
        w = _world()
        fast_prey = _spawn_neque(r, speed=99.0)  # escapa a un tigrillo
        aguila = _spawn_aguila(r, energy=50)
        ctx = _ctx(r, w, seed=3)
        PredatorSystem().update(ctx)
        # Águila: éxito = 1 - camo = 0.9 -> rng.random() < 0.9 muy probable.
        # No determinista frágil: con seed 3 el sorteo cae < 0.9.
        assert r.get_component(fast_prey, EnergyComponent).current_energy == 0
        assert (
            r.get_component(aguila, EnergyComponent).current_energy
            == 50 + HUNT_ENERGY_GAIN
        )

    def test_predator_loses_energy_without_prey(self):
        r = Registry()
        w = _world()
        pred = _spawn_tigrillo(r, energy=50)
        PredatorSystem().update(_ctx(r, w))
        # -1 por esfuerzo sin presa (solo gasta mucho si alcanza a cazar).
        assert r.get_component(pred, EnergyComponent).current_energy == 49

    def test_predator_wanders_when_hungry(self):
        r = Registry()
        w = _world()
        pred = _spawn_tigrillo(r, x=5, y=5, energy=50, speed=16.0)
        ctx = _ctx(r, w, seed=1)
        positions = set()
        for _ in range(5):
            PredatorSystem().update(ctx)
            pos = r.get_component(pred, Position)
            positions.add((pos.x, pos.y))
        # En 5 vagarros con jitter de ±4, debe acumular más de una posición.
        assert len(positions) > 1

    def test_pipeline_tigrillo_kills_neque_deathsystem_removes(self):
        r = Registry()
        w = _world()
        prey = _spawn_neque(r, speed=4.0)
        _spawn_tigrillo(r, speed=10.0)
        ctx = _ctx(r, w)
        PredatorSystem().update(ctx)
        DeathSystem().update(ctx)
        assert prey not in set(r.alive_entities())
