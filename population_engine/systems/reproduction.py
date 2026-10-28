"""ReproductionSystem: budding/cloning for well-fed animals (S3 minimal).

Rules (intentionally simple, ran AFTER feeding/predation):

* Any entity with an ``EnergyComponent`` and a ``GenomeComponent`` whose
  ``current_energy >= REPRO_THRESHOLD`` may reproduce this tick with
  probability ``REPRO_PROB`` (drawn from the shared ``ctx.rng``).
* The parent pays ``REPRO_COST`` energy; the child is a clone (same species,
  diet, genome) placed within ``CHILD_OFFSET`` cells of the parent, with
  half the parent's post-cost energy (clamped to ints).
* If ``population_block()`` returns True (noise lever of HumanPressureSystem
  reports reproduction suppressed), no births happen this tick.

Structural changes follow the ADR-004 interim pattern (same as DeathSystem):
candidates are collected during the query, entities are created only after the
query iterator is exhausted. When the engine's structural-request queue lands,
convert the spawn loop to queued requests.
"""

from __future__ import annotations

from ..ecs.components import (
    Diet,
    EnergyComponent,
    GenomeComponent,
    PhenotypeComponent,
    Position,
    SpeciesRef,
)
from ..ecs.enums import DietType
from ..ecs.scheduler import System, SystemContext

__all__ = ["ReproductionSystem", "REPRO_THRESHOLD", "REPRO_PROB", "REPRO_COST"]

REPRO_THRESHOLD: int = 85     # energía mínima para reproducirse
REPRO_PROB: float = 0.02      # prob. por tick NOMINAL (el espacio la modula)
REPRO_COST: int = 40          # energía que paga el padre
CHILD_OFFSET: int = 3         # dispersión máxima de la cría
REPRO_MIN_COOLDOWN: int = 52  # semanas mínimas entre crías (1 año)
MAX_BIRTHS_PER_TICK: int = 2  # límite global de crías por semana (control poblacional)

#: Especies cuya población la controla DIRECTAMENTE el usuario (no se
#: reproducen solas): mascotas y cazadores. Así el input de cantidad de la
#: UI permanece estable semana a semana.
NO_SELF_REPRODUCTION: frozenset[str] = frozenset({"feral", "cazador"})


class ReproductionSystem(System):
    """Clone well-fed entities; noise lever suppresses mating entirely."""

    name = "reproduction"
    reads: tuple = (
        SpeciesRef, Diet, GenomeComponent, PhenotypeComponent, Position, EnergyComponent,
    )
    writes: tuple = (EnergyComponent,)
    after: tuple = ("predators",)

    def __init__(self, population_block=None, rng=None, world_size: int = 128,
                 space_getter=None) -> None:
        # ``population_block``: callable -> bool; ui lo conecta a
        # human_pressure.reproduction_suppressed.
        # ``space_getter``: callable(species_id) -> float 0..1; el slider de
        # "espacio" de la UI modula la tasa de nacimientos por especie.
        self._population_block = population_block or (lambda: False)
        self._space_getter = space_getter or (lambda _sid: 1.0)
        self._world_size = int(world_size)
        # Semana del último parto por entidad (cooldown realista).
        self._last_birth: dict = {}

    def update(self, ctx: SystemContext) -> None:
        if self._population_block():
            return
        rng = ctx.rng
        if rng is None:
            return
        registry = ctx.registry
        week = ctx.clock.now().tick if ctx.clock is not None else 0

        # Fase 1: recolectar candidatos (sin tocar estructura).
        candidates = []
        query = registry.query(
            SpeciesRef, Diet, GenomeComponent, PhenotypeComponent, Position, EnergyComponent,
        )
        for entity, sref, diet, genome, pheno, pos, energy in query:
            if not sref.species_id:
                continue                       # plantas: fuera de alcance
            if sref.species_id in NO_SELF_REPRODUCTION:
                continue                       # mascotas/cazadores: los fija el usuario
            if energy.current_energy < REPRO_THRESHOLD:
                continue
            # Cooldown: un individuo no puede tener crías cada semana.
            if week - self._last_birth.get(entity, -999) < REPRO_MIN_COOLDOWN:
                continue
            # El espacio slider modula la probabilidad (0 = no nacen).
            space_factor = self._space_getter(sref.species_id)
            if space_factor <= 0.0:
                continue
            if rng.random() < REPRO_PROB * space_factor:
                candidates.append((entity, sref, diet, genome, pheno, pos, energy))
        # Límite global de nacimientos por tick (una especie no puede parir
        # 20 crías en una semana aunque estén muy bien alimentadas).
        candidates = candidates[:MAX_BIRTHS_PER_TICK]

        # Fase 2: aplicar coste y crear crías tras agotar la query.
        limit = self._world_size - 1
        for entity, sref, diet, genome, pheno, pos, energy in candidates:
            energy.current_energy -= REPRO_COST
            child_energy = max(1, energy.current_energy // 2)
            energy.current_energy -= child_energy
            self._last_birth[entity] = week
            ox = int(rng.integers(-CHILD_OFFSET, CHILD_OFFSET + 1))
            oy = int(rng.integers(-CHILD_OFFSET, CHILD_OFFSET + 1))
            registry.create_entity(
                Position(x=max(0, min(limit, pos.x + ox)),
                         y=max(0, min(limit, pos.y + oy))),
                SpeciesRef(species_id=sref.species_id),
                GenomeComponent(genes=dict(genome.genes),
                                mutation_rate=genome.mutation_rate),
                PhenotypeComponent(camouflage=pheno.camouflage,
                                   cold_resistance=pheno.cold_resistance,
                                   speed=pheno.speed),
                EnergyComponent(current_energy=child_energy,
                                max_energy=energy.max_energy),
                Diet(diet_type=diet.diet_type),
            )
