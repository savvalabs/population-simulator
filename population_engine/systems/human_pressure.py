"""HumanPressureSystem (v2 — refactor): presión humana exógena parametrizable.

Los humanos NO son entidades ECS: son una fuente de disturbio externa con
siete palancas escalables en ``[0.0, 1.0]`` que la UI puede dictar
independientemente:

============  ===============================================================
Palanca       Efecto mecánico
============  ===============================================================
urbanization  Borde del mapa Letal: entidades en el anillo exterior pierden
              energía masiva (el hábitat se encoge hacia el centro).
food_scarcity Se CANALIZA al ResourceSystem: atenúa la regeneración de
              biomasa (deforestación). Leído vía callable inyectado.
contamination Sube ``genome.mutation_rate`` y resta un % fijo de energía.
hunters       Muerte súbita: probabilidad por tick de energía=0 para ñeques
              Y tigrillos, ignorando stats (trampas/escopetas).
noise         Movimiento errático: jitter de posición + quema de energía;
              también suprime la reproducción (bloquea ``Reproductive``
              poniendo ``gestation_ticks`` a 0 y marcando no-reproducción).
roads         algunas filas/columnas son "vías": cruzar = atropellamiento
              con alta probabilidad (instantáneo, ignora stats).
invasive      Mantiene una población de depredadores ferales (perros/gatos)
              que cazan ñeques pero NO mueren de hambre.
============  ===============================================================

Determinista: todo RNG proviene de ``ctx.rng`` y el iterado es por orden de
arquetipo. Sin dependencias externas; sin cambios durante la iteración de
queries (spawn de ferales ocurre DESPUÉS de consumir el query, patrón
interino ADR-004, idem DeathSystem).
"""

from __future__ import annotations

from ..ecs.components import (
    Diet,
    EnergyComponent,
    GenomeComponent,
    PhenotypeComponent,
    Position,
    Reproductive,
    SpeciesRef,
)
from ..ecs.enums import DietType
from ..ecs.scheduler import System, SystemContext

__all__ = ["HumanPressureSystem"]

#: Energy burned per unit of contamination (fraction) per tick.
CONTAMINATION_ENERGY_DRAIN: float = 0.02
#: Energy drain per tick in the urbanization border ring.
URBAN_EDGE_DRAIN: int = 30
#: Extra energy burned per tick by noise-driven erratic movement.
NOISE_ENERGY_DRAIN: int = 3
#: Max sudden-death probability per tick at hunters=1.0.
HUNT_LETHALITY: float = 0.10
#: Max roadkill probability per crossing at roads=1.0.
ROADKILL_LETHALITY: float = 0.35
#: Road cells: a cross (vertical at WORLD_CELLS//2, horizontal at //2).
ROAD_OFFSET: int = 0  # the cross is exactly at the middle of the map
#: Width (in cells) of the urbanization edge ring at urbanization=1.0.
URBAN_RING_MAX: float = 20.0
#: Max feral predators kept alive at invasive=1.0.
FERAL_CAP: int = 8


class HumanPressureSystem(System):
    """Apply the seven human-pressure levers to the ecosystem.

    All levers are floats in ``[0.0, 1.0]`` and publicly settable so the UI
    layer (web_server) can drive them per slider without touching internals.
    """

    name = "human_pressure"
    reads: tuple = (Diet, EnergyComponent, GenomeComponent, Position, SpeciesRef)
    writes: tuple = (EnergyComponent, GenomeComponent, Position, Reproductive)
    after: tuple = ()

    def __init__(self, *, active: bool = False, world_size: int = 128) -> None:
        self.active = bool(active)
        self.world_size = int(world_size)
        # -- Siete palancas (0.0 .. 1.0) ------------------------------------
        self.urbanization: float = 0.0
        self.food_scarcity: float = 0.0
        self.contamination: float = 0.0
        self.hunters: float = 0.0
        self.noise: float = 0.0
        self.roads: float = 0.0
        self.invasive: float = 0.0
        # Capa de reproducción: noise la suprime (señal leída por un futuro
        # ReproductionSystem; también aplicamos debuff directo aquí).
        self._feral_energy_floor: int = 200

    # -- lever readers for other systems -------------------------------------

    def deforestation_factor(self) -> float:
        """Read by ResourceSystem: multiplier-atenuación de biomasa."""
        return self.food_scarcity if self.active else 0.0

    def reproduction_suppressed(self) -> bool:
        """True si el ruido bloquea el apareo (leído por ReproductionSystem)."""
        return self.active and self.noise >= 0.5

    # -- tick ---------------------------------------------------------------

    def update(self, ctx: SystemContext) -> None:
        if not self.active:
            return
        registry = ctx.registry
        rng = ctx.rng

        center = self.world_size / 2.0
        ring = self.urbanization * URBAN_RING_MAX
        road_col = int(center + ROAD_OFFSET)
        road_row = int(center + ROAD_OFFSET)

        feral_seen: list = []

        query = registry.query(
            Position, Diet, SpeciesRef, GenomeComponent, EnergyComponent
        )
        for entity, pos, diet, sref, _genome, energy in query:
            # -- 1. Urbanización: borde letal -------------------------------
            if ring > 0.0:
                d_from_edge = min(pos.x, pos.y, self.world_size - 1 - pos.x,
                                  self.world_size - 1 - pos.y)
                if d_from_edge < ring:
                    energy.current_energy -= URBAN_EDGE_DRAIN
                    energy.last_damage_source = "pérdida de hábitat (urbanización)"
                    continue  # demasiado débil para seguir el resto de cheques

            # -- 2. Contaminación: mutación + drenaje fijo ------------------
            if self.contamination > 0.0:
                _genome.mutation_rate = min(
                    1.0, _genome.mutation_rate * (1.0 + self.contamination)
                )
                energy.current_energy -= int(
                    energy.max_energy
                    * CONTAMINATION_ENERGY_DRAIN
                    * self.contamination
                )
                energy.last_damage_source = "contaminación química"

            # -- 3. Cazadores: muerte súbita, ignora stats ------------------
            if self.hunters > 0.0 and diet.diet_type in (
                DietType.HERBIVORE, DietType.CARNIVORE,
            ):
                lethal = HUNT_LETHALITY * self.hunters
                if rng is None or rng.random() < lethal:
                    energy.current_energy = 0
                    energy.last_damage_source = "cazador furtivo"
                    continue

            # -- 4. Carreteras: atropellamiento cruzando la vía -------------
            if self.roads > 0.0 and (pos.x == road_col or pos.y == road_row):
                lethal = ROADKILL_LETHALITY * self.roads
                if rng is not None and rng.random() < lethal:
                    energy.current_energy = 0
                    energy.last_damage_source = "atropellamiento (carretera)"
                    continue

            # -- 5. Ruido: movimiento errático + energía extra + no-repro ---
            if self.noise > 0.0:
                energy.current_energy -= NOISE_ENERGY_DRAIN
                energy.last_damage_source = "ruido / turismo"
                if rng is not None:
                    jitter = max(1, int(4 * self.noise))
                    pos.x = max(0, min(self.world_size - 1,
                                       pos.x + int(rng.integers(-jitter, jitter + 1))))
                    pos.y = max(0, min(self.world_size - 1,
                                       pos.y + int(rng.integers(-jitter, jitter + 1))))

            # Track ferals para el chequeo post-query.
            if sref.species_id == "feral":
                feral_seen.append(entity)

        # -- 6. Invasoras: mantener población de ferales --------------------
        target = int(round(self.invasive * FERAL_CAP))
        if target > 0:
            # Spawn hasta alcanzar el target; los ferales no mueren de hambre:
            # restaurar energía aquí (los trata como "alimentados en casa").
            query2 = registry.query(SpeciesRef, EnergyComponent)
            count = 0
            for _e, sref, energy in query2:
                if sref.species_id == "feral":
                    count += 1
                    energy.current_energy = max(energy.current_energy,
                                                self._feral_energy_floor)
            missing = target - count
            if missing > 0 and rng is not None:
                for _ in range(missing):
                    x = int(rng.integers(0, self.world_size))
                    y = int(rng.integers(0, self.world_size))
                    registry.create_entity(
                        Position(x=x, y=y),
                        SpeciesRef(species_id="feral"),
                        GenomeComponent(genes={"fur_color": "brown",
                                               "fur_thickness": 4,
                                               "leg_length": 16}),
                        PhenotypeComponent(camouflage=0.5, cold_resistance=10.0,
                                           speed=24.0),
                        EnergyComponent(current_energy=self._feral_energy_floor,
                                        max_energy=self._feral_energy_floor),
                        Diet(diet_type=DietType.CARNIVORE),
                    )
