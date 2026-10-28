"""ForagingSystem + PredatorSystem: the Ñeque trophic chain (S3).

* **ForagingSystem** — herbívoros (Ñeques): consume biomass of their cell to
  restore ``EnergyComponent.current_energy``. Empty cell -> they lose energy
  and wander up to ``int(speed)`` cells (Manhattan) towards richer pasture.
* **PredatorSystem** — carnívoros comparten celda con presas. Dos cacerías:
    - ``tigrillo`` (terrestre): chequeo de velocidad — si
      ``predator.speed >= prey.speed``, caza; la presa va a energía 0 y el
      depredador restaura energía.
    - ``aguila`` (aéreo): chequeo de percepción — usa ``ctx.rng`` contra
      ``prey.camouflage``; ignora terreno/velocidad. Marca: ``SpeciesRef``.
    - ``feral`` (perros/gatos, creados por HumanPressure): matan ñeques igual
      que tigrillos pero NO mueren de hambre (HumanPressure los alimenta).

Sin cambios estructurales durante la iteración: las entidades cazadas se dejan
a energía <= 0 y DeathSystem las recolecta; los spawns de ``feral`` los hace
HumanPressureSystem fuera de los bucles de query (patrón interino ADR-004).
Determinista: el orden de queries es dérítreblo del Registry y el RNG es el
``ctx.rng`` compartido, consumido siempre en el mismo orden por celda.
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
from ..world.coords import CellCoord

__all__ = ["ForagingSystem", "PredatorSystem",
           "EAT_AMOUNT", "HUNT_ENERGY_GAIN", "PREDATOR_SPEED_BONUS"]

EAT_AMOUNT: float = 20.0        # biomasa consumida por tick por ñeque
STARVE_LOSS: int = 8            # energía perdida si la celda está pelada
HUNT_ENERGY_GAIN: int = 40      # energía que gana el depredador al cazar
PREDATOR_SPEED_BONUS: float = 1.2   # tigrillo ligeramente más rápido
MOVE_PER_SPEED: int = 4         # 1 celda por cada 4 puntos de speed

#: Presas que cada depredador puede cazar (lo dicta la tabla trófica; los
#: tigrillos NO cazan pajaritos — éstos solo los cazan las águilas).
PREDATOR_PREY: dict[str, frozenset[str]] = {
    "tigrillo": frozenset({"neque", "roedor", "insecto"}),
    "aguila":   frozenset({"neque", "pajarito", "roedor", "insecto"}),
    "feral":    frozenset({"neque", "roedor"}),   # perros/gatos
    "cazador":  frozenset({"neque", "tigrillo"}),  # trampas/escopetas
    "serpiente": frozenset({"roedor", "pajarito", "insecto"}),
}


class ForagingSystem(System):
    """Herbivores eat biomass; starve and wander if the cell is bare."""

    name = "foraging"
    reads: tuple = (Diet, PhenotypeComponent)
    writes: tuple = (EnergyComponent, Position)
    # Reads biomass written by ResourceSystem AND its own writes move Position,
    # which ExposureSystem reads NEXT tick. Non-component deps are explicit.
    after: tuple = ("resources", "exposure")

    def update(self, ctx: SystemContext) -> None:
        world = ctx.world
        if world is None:
            return
        from ..ecs.components import SpeciesRef as _SpeciesRef
        query = ctx.registry.query(
            Position, Diet, PhenotypeComponent, EnergyComponent, _SpeciesRef
        )
        for _e, pos, diet, pheno, energy, sref in query:
            if diet.diet_type is not DietType.HERBIVORE:
                continue
            # Las plantas no "comen" biomasa — ellas la SON. Tampoco se mueven.
            if sref is not None and sref.species_id == "planta":
                continue
            cell = CellCoord(pos.x, pos.y)
            available = float(world.value("biomass", cell))
            if available >= EAT_AMOUNT:
                # Consume and digest.
                self._set_biomass(world, cell, available - EAT_AMOUNT)
                energy.current_energy = min(
                    energy.max_energy,
                    energy.current_energy + int(EAT_AMOUNT),
                )
            else:
                # Comer lo poco que hay (si hay) y pasar hambre.
                if available > 0:
                    # Con clamp: no sobrepasar max_energy al comer restos.
                    energy.current_energy = min(
                        energy.max_energy,
                        energy.current_energy + int(available),
                    )
                    self._set_biomass(world, cell, 0.0)
                energy.current_energy -= STARVE_LOSS
                energy.last_damage_source = "hambruna (sin biomasa)"
                # Vagar en busca de comida: speed fenotípico dicta el rango.
                self._wander(ctx, pos, pheno.speed)

    @staticmethod
    def _set_biomass(world, cell: CellCoord, value: float) -> None:
        chunk = world.chunk(cell.to_chunk(world.chunk_size))
        lx, ly = cell.local_offset(world.chunk_size)
        chunk.field("biomass").interior[ly, lx] = value

    def _wander(self, ctx: SystemContext, pos: Position, speed: float) -> None:
        rng = ctx.rng
        if rng is None:
            return
        world = ctx.world
        limit = world.width_chunks * world.chunk_size - 1  # celdas válidas 0..limit
        steps = max(1, int(speed / MOVE_PER_SPEED))
        pos.x = int(rng.integers(max(0, pos.x - steps), min(limit, pos.x + steps) + 1))
        pos.y = int(rng.integers(max(0, pos.y - steps), min(limit, pos.y + steps) + 1))


class PredatorSystem(System):
    """Cacería en celda compartida. Tigrillos por velocidad; águilas por camo."""

    name = "predators"
    reads: tuple = (Diet, PhenotypeComponent, SpeciesRef)
    writes: tuple = (EnergyComponent,)
    # Posiciones ya asentadas tras el forrajeo.
    after: tuple = ("foraging",)

    def update(self, ctx: SystemContext) -> None:
        registry = ctx.registry
        rng = ctx.rng

        # Snapshot de presas por celda (para no iterar la misma estructura
        # que modificamos durante las cazas).
        query = registry.query(Position, Diet, SpeciesRef, PhenotypeComponent, EnergyComponent)
        prey_by_cell: dict[tuple[int, int], list] = {}
        predators: list = []
        for entity, pos, diet, sref, pheno, energy in query:
            key = (pos.x, pos.y)
            if diet.diet_type is DietType.HERBIVORE:
                prey_by_cell.setdefault(key, []).append((entity, sref, pheno, energy))
            elif diet.diet_type is DietType.CARNIVORE:
                predators.append((entity, pos, sref, pheno, energy))

        world = ctx.world
        limit = (
            world.width_chunks * world.chunk_size - 1
            if world is not None else None
        )
        for pred_entity, pos, sref, pheno, energy in predators:
            key = (pos.x, pos.y)
            prey_list = prey_by_cell.get(key)
            # Presas válidas para ESTE depredador en esta celda.
            allowed = PREDATOR_PREY.get(sref.species_id, frozenset())
            if prey_list:
                prey_list = [
                    p for p in prey_list
                    if p[1].species_id in allowed and p[3].current_energy > 0
                ]
            if not prey_list:
                # Sin presas en la celda: olfatea la presa VIVA más cercana y
                # se dirige a ella (rango Manhattan = speed/4).
                energy.current_energy -= 1
                # Etiqueta diagnóstica: sin esto, un depredador que muere de
                # inanición llega al DeathSystem con la causa vacía y el log
                # reporta "causa desconocida" (bug de extinciones ilegibles).
                energy.last_damage_source = "hambre (sin presas)"
                if rng is not None and pheno.speed > 0:
                    steps = max(1, int(pheno.speed / MOVE_PER_SPEED))
                    target = None
                    best = None
                    for (px, py), plist in prey_by_cell.items():
                        # Presa VIVA y de una especie que CACE este depredador.
                        if not any(
                                pe.current_energy > 0 and ps.species_id in allowed
                                for _, ps, _, pe in plist
                        ):
                            continue
                        dist = abs(px - pos.x) + abs(py - pos.y)
                        if best is None or dist < best:
                            best = dist
                            target = (px, py)
                    if target is not None:
                        # Paso dirigido hacia la presa (Manhattan, cap=steps).
                        dx = max(-steps, min(steps, target[0] - pos.x))
                        dy = max(-steps, min(steps, target[1] - pos.y))
                        pos.x += dx
                        pos.y += dy
                    else:
                        # Sin presas vivas en el mapa: vagar de hambre.
                        nx = pos.x + int(rng.integers(-steps, steps + 1))
                        ny = pos.y + int(rng.integers(-steps, steps + 1))
                        pos.x = nx
                        pos.y = ny
                if limit is not None:
                    pos.x = max(0, min(limit, pos.x))
                    pos.y = max(0, min(limit, pos.y))
                continue

            is_aerial = sref.species_id == "aguila"
            hunted = None
            for prey_entity, prey_sref, prey_pheno, prey_energy in prey_list:
                if prey_sref.species_id not in allowed:
                    continue
                if prey_energy.current_energy <= 0:
                    continue  # ya muerto este tick, siguiente
                if is_aerial:
                    # Águila: éxito = 1 - camouflage de la presa (percepción).
                    success_prob = max(0.0, min(1.0, 1.0 - prey_pheno.camouflage))
                    success = (rng is None) or (rng.random() < success_prob)
                else:
                    # Terrestre / feral: carrera de velocidad.
                    success = pheno.speed >= prey_pheno.speed * PREDATOR_SPEED_BONUS
                if success:
                    hunted = (prey_entity, prey_energy)
                    break
            if hunted is not None:
                prey_entity, prey_energy = hunted
                prey_energy.current_energy = 0  # DeathSystem lo retira
                prey_energy.last_damage_source = f"cazado ({sref.species_id})"
                energy.current_energy = min(
                    energy.max_energy, energy.current_energy + HUNT_ENERGY_GAIN
                )
