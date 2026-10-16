"""Puente web (opción B): expone el Engine real al mockup HTML vía JSON.

Arquitectura cliente-servidor liviana, SOLO stdlib (sin dependencias nuevas;
pygame se queda para la UI local y no interviene aquí):

* GET  /                    -> el mockup HTML (diseño intacto).
* POST /api/tick            -> avanza 1 tick (1 semana) y devuelve el estado.
* POST /api/population      -> {species, action, qty} agrega/quita individuos.
* POST /api/climate         -> {mode: sequia|lluvia|caos} ajusta el clima base.
* POST /api/env             -> {comida, espacio, contaminacion, enfermedades}
* POST /api/reset           -> reconstruye el Engine desde cero.
* GET  /api/state           -> snapshot JSON sin avanzar.

Mapeo mockup -> motor (simplificación declarada; el mockup es por-especie y el
motor por-individuo, ver notes del Arquitecto):

* "neques"    -> herbívoros (Genome+Phenotype+Energy, Diet HERBIVORE)
* "tigrillos" -> depredadores (Diet CARNIVORE)
* "pajaritos" -> plantas (Position sin Genome)
* "aguilas"   -> depredadores aéreos (ignoran terreno)
* "cazadores" -> entidades ECS reales (cazan ñeques y tigrillos con sus propias
                 posiciones, energy y genoma; véase `PopulationGenerator.cazadores`).
                 NOTA: la palanca de presión humana "hunters" es OTRO concepto
                 (probabilidad global de muerte por inanición humana aplicada a
                 herbívoros y carnívoros — no es LA POBLACIÓN de cazadores).

Compatibilidad multi-dispositivo: cualquier navegador que llegue al host.
Arranque:  python web_server.py  ->  http://localhost:8000
"""

from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from population_engine.core.config import EngineConfig
from population_engine.core.engine import Engine
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
from population_engine.ecs.scheduler import Scheduler
from population_engine.systems.climate import ClimateSystem, UniformBiomeProvider
from population_engine.systems.death import DeathSystem, EntityDied
from population_engine.systems.environment_exposure import ExposureSystem
from population_engine.systems.environment_pressure import EnvironmentPressureSystem
from population_engine.systems.genetics import GeneticsSystem
from population_engine.systems.human_pressure import HumanPressureSystem
from population_engine.systems.predators import ForagingSystem, PredatorSystem
from population_engine.systems.reproduction import ReproductionSystem
from population_engine.systems.resources import ResourceSystem
from population_engine.systems.species_env import SpeciesEnvSystem
from population_engine.world.coords import ChunkCoord
from population_engine.world.world import World

HTML_PATH = Path(__file__).with_name("gemini-code-1789928335378.html")

WORLD_CHUNKS = 4
CHUNK_SIZE = 32
WORLD_CELLS = WORLD_CHUNKS * CHUNK_SIZE  # 128
WEEKS_PER_GENERATION = 52
MAX_VISUAL_PER_SPECIES = 50

SPECIES_KEYS = ("neques", "tigrillos", "aguilas", "feral", "cazadores", "pajaritos")

#: Especies de "ecosistema de fondo": existen en el ECS (comen, cazan/me hacen
#: presa, se reproducen) pero NO aparecen en la UI (sin tarjeta, sin emoji).
BACKGROUND_SPECIES = ("planta", "insecto", "roedor", "serpiente")

# Climas del mockup -> parámetros base del UniformBiomeProvider.
# Climas del mockup -> parámetros base del UniformBiomeProvider.
# "normal" = promedio de la Sierra Nevada de Santa Marta. Las estaciones
# seca/lluviosa las aplica el ClimateModel (offsets estacionales ya definidos
# en models/climate.py: lluvia -2°C, suelo +0.1 humedad, precipitación ×1.5/0.5).
CLIMATE_PRESETS = {
    "normal": dict(base_temperature=22.0, base_humidity=0.55),
    "sequia": dict(base_temperature=28.0, base_humidity=0.15),
    "lluvia": dict(base_temperature=20.0, base_humidity=0.65),
    "caos": dict(base_temperature=-5.0, base_humidity=0.5),
}


class Simulation:
    """Singleton de servidor: dueño del Engine y del mapeo de especies."""

    def __init__(self, seed: int = 7) -> None:
        self.seed = seed
        self._climate_mode = "normal"
        # RLock (no Lock simple): public methods like tick()/modify_population/
        # reset() call snapshot() internally; a plain Lock would self-deadlock.
        self._lock = threading.RLock()
        self.rebuild()
        self.event_log: list[str] = []
        # Causas de muerte agregadas por especie (para "por qué se extinguió").
        self._death_causes: dict[str, dict[str, int]] = {}
        self._prev_populations: dict[str, int] = {}

    def _on_entity_died(self, event: EntityDied) -> None:
        """Subscriber del EventBus: acumula causas y reporta extinciones."""
        bucket = self._death_causes.setdefault(event.species_id, {})
        bucket[event.cause] = bucket.get(event.cause, 0) + 1

    def rebuild(self) -> None:
        self._climate_mode = "normal"
        registry = Registry()
        events = EventBus()
        world = World(
            width_chunks=WORLD_CHUNKS,
            height_chunks=WORLD_CHUNKS,
            chunk_size=CHUNK_SIZE,
        )
        scheduler = Scheduler()
        self.biome_provider = UniformBiomeProvider(**CLIMATE_PRESETS["normal"])
        self.human_pressure = HumanPressureSystem(world_size=WORLD_CELLS)
        self.species_env = SpeciesEnvSystem(world_size=WORLD_CELLS)
        for system in (
            GeneticsSystem(),
            ClimateSystem(biome_provider=self.biome_provider),
            ExposureSystem(),
            ResourceSystem(
                deforestation_getter=self.human_pressure.deforestation_factor
            ),
            ForagingSystem(),
            PredatorSystem(),
            ReproductionSystem(
                population_block=self.human_pressure.reproduction_suppressed,
                space_getter=self.species_env.reproduction_factor,
            ),
            EnvironmentPressureSystem(),
            # Por-especie después del estrés ambiental genérico.
            self.species_env,
            self.human_pressure,
            DeathSystem(),
        ):
            scheduler.add_system(system)
        scheduler.build()
        self.engine = Engine(
            EngineConfig(seed=self.seed, ticks_per_day=1),  # 1 tick = 1 semana
            registry=registry,
            scheduler=scheduler,
            events=events,
            world=world,
        )
        self.engine.start()
        self.registry = registry
        self.event_log = []
        # Cuando DeathSystem recolecte, acumulamos causa por especie (para
        # el mensaje de extinción en el log).
        self._death_causes = {}
        self._prev_populations = {}
        events.subscribe(EntityDied, self._on_entity_died)
        self._spawn_background_population()

    def _spawn_initial_biomass(self) -> None:
        """Biomasa inicial de 50 por celda (pradera moderada)."""
        for iy in range(self.engine._world.height_chunks):
            for ix in range(self.engine._world.width_chunks):
                self.engine._world.chunk(ChunkCoord(ix, iy)).field("biomass").interior[...] = 50.0

    def _spawn_background_population(self) -> None:
        """Organismos que habitan el bioma SIEMPRE (aunque no se vean).

        Su función ecológica: dan de comer a los depredadores, mantienen la
        biomasa y crean la presión ambiental de fondo. No llevan tarjeta ni
        emoji — no se renderizan.
        """
        genomes = {
            # plantas: SIN genoma/fenotipo/energía — son el sustrato biomasa,
            # inmunes al frío (no son presas). El fondo queda vivo siempre.
            "insecto":   {"fur_color": "brown", "fur_thickness": 3, "leg_length": 6},
            "roedor":    {"fur_color": "brown", "fur_thickness": 5, "leg_length": 10},
            "serpiente": {"fur_color": "brown", "fur_thickness": 8, "leg_length": 2},
        }
        counts = {"planta": 200, "insecto": 80, "roedor": 40, "serpiente": 10}
        rng = self.engine.rng
        for sid, n in counts.items():
            for _ in range(n):
                x = int(rng.integers(0, WORLD_CELLS))
                y = int(rng.integers(0, WORLD_CELLS))
                if sid == "planta":
                    # Planta = presencia estática de biomasa automática (no come,
                    # no se mueve, no envejece). Solo posición + etiqueta.
                    self.registry.create_entity(
                        Position(x=x, y=y),
                        SpeciesRef(species_id="planta"),
                    )
                    continue
                genes = genomes[sid]
                self.registry.create_entity(
                    Position(x=x, y=y),
                    SpeciesRef(species_id=sid),
                    GenomeComponent(genes=dict(genes)),
                    PhenotypeComponent(),
                    EnergyComponent(current_energy=50, max_energy=60),
                    Diet(diet_type=(
                        DietType.CARNIVORE if sid == "serpiente"
                        else DietType.HERBIVORE
                    )),
                )

        # Biomasa inicial: pradera moderada para arrancar la cadena trófica.
        self._spawn_initial_biomass()

    # -- acciones -----------------------------------------------------------

    def _live_population_counts(self) -> dict[str, int]:
        pops = {k: 0 for k in SPECIES_KEYS}
        for entity, _pos in self.registry.query(Position):
            sp = self._species_of(entity)
            if sp is not None:
                pops[sp] += 1
        return pops

    def tick(self) -> dict:
        with self._lock:
            prev = self._live_population_counts()
            self.engine.tick()
            snap = self.snapshot()
            # Detección de extinción con causa dominante (enviada al log).
            for sp in SPECIES_KEYS:
                if prev.get(sp, 0) > 0 and snap["populations"].get(sp, 0) == 0:
                    # Las claves de _death_causes son species_id singulares
                    # ('neque'), pero SPECIES_KEYS usa el plural del mockup.
                    singular = sp[:-1] if sp.endswith('s') else sp
                    causes = self._death_causes.get(singular, {}) or \
                             self._death_causes.get(sp, {})
                    self._death_causes[singular] = {}   # reset tras reportar
                    self._death_causes[sp] = {}
                    if causes:
                        dominant = max(causes, key=causes.get)
                        self.log(
                            f"💀 Extinción de {sp}: causa dominante = {dominant}"
                        )
                    else:
                        self.log(f"💀 Extinción de {sp} (sin causa registrada)")
            return snap

    def snapshot(self) -> dict:
        # Lectura atómica: ThreadingHTTPServer sirve /api/state y mutaciones
        # concurrentes; el lock evita snapshots tomados a mitad de un tick.
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict:
        """Lógica de snapshot SIN lock (solo llamar con el lock adquirido)."""
        populations = {k: 0 for k in SPECIES_KEYS}
        entities = {k: [] for k in SPECIES_KEYS}
        for entity, pos in self.registry.query(Position):
            sref = self.registry.get_component(entity, SpeciesRef)
            species_id = sref.species_id if (sref and sref.species_id) else "planta"
            sp = self._species_of(entity)
            if sp is None:
                continue            # especies de fondo: no van a la UI
            populations[sp] += 1
            if len(entities[sp]) < MAX_VISUAL_PER_SPECIES:
                entities[sp].append(
                    {
                        "left": round(pos.x / WORLD_CELLS * 100, 2),
                        "top": round(pos.y / WORLD_CELLS * 100, 2),
                        "sid": species_id,  # species_id REAL para formas (feral, etc.)
                    }
                )
        weeks = self.engine.ticks_executed
        return {
            "week": weeks,
            "year": weeks // WEEKS_PER_GENERATION,
            "generation": weeks // WEEKS_PER_GENERATION,
            "populations": populations,
            "entities": entities,
            "biomass": self._biomass_grid(),   # 32x32, valores 0..100
            "human_pressure_active": self.human_pressure.active,
            "species_env": {
                sp: self.species_env.get_config(sp)
                for sp in ("neque", "tigrillo", "aguila", "pajarito", "feral")
            },
            "climate_mode": self._climate_mode,
            "levers": {
                "urbanization": self.human_pressure.urbanization,
                "food_scarcity": self.human_pressure.food_scarcity,
                "contamination": self.human_pressure.contamination,
                "hunters": self.human_pressure.hunters,
                "noise": self.human_pressure.noise,
                "roads": self.human_pressure.roads,
                "invasive": self.human_pressure.invasive,
            },
            "log": self.event_log[-30:],
        }

    def set_climate(self, mode: str) -> dict:
        with self._lock:
            self._climate_mode = mode
            preset = CLIMATE_PRESETS.get(mode, CLIMATE_PRESETS["normal"])
            self.biome_provider.base_temperature = preset["base_temperature"]
            self.biome_provider._bh = float(preset["base_humidity"])
            self.log(f"🌦 Clima: {mode}")
            return self.snapshot()

    def set_env(self, env: dict) -> dict:
        """LEGACY: el panel global de Entorno. Mantener compatibilidad."""
        with self._lock:
            hp = self.human_pressure
            hp.urbanization = (10 - int(env.get("espacio", 10))) / 10.0
            hp.food_scarcity = (10 - int(env.get("comida", 10))) / 10.0
            self.log(f"🌫 Env global: urban={hp.urbanization:.2f} food_scarcity={hp.food_scarcity:.2f}")
            return self.snapshot()

    def set_species_env(self, species_id: str, values: dict) -> dict:
        """Actualiza la configuración POR ESPECIE (los sliders por animal)."""
        with self._lock:
            self.species_env.set_config(species_id, values)
            self.log(f"⚙️ Env {species_id}: {values}")
            return self.snapshot()

    def modify_population(
        self, species: str, action: str, qty: int
    ) -> dict:
        with self._lock:
            qty = max(1, int(qty))
            if action == "add":
                self._spawn(species, qty)
                self.log(f"➕ +{qty} {species}")
            else:
                removed = self._remove(species, qty)
                self.log(f"➖ -{removed} {species}")
            return self.snapshot()

    def reset(self) -> dict:
        """Reset TOTAL: motor + palancas + logs.

        ``rebuild()`` recrea TODO desde cero (Registry, World, Scheduler,
        Engine) con la misma seed. Las palancas de presión humana y las
        configuraciones por especie quedan en sus defaults — así que un
        reset realmente deja un mundo limpio (y el cliente alinea la UI).
        """
        with self._lock:
            self.rebuild()
            self.log("🔄 Simulación reiniciada (Engine reconstruido; palancas/sliders a defaults)")
            return self.snapshot()

    def log(self, msg: str) -> None:
        self.event_log.append(msg)
        del self.event_log[:-100]

    # -- helpers de población ----------------------------------------------

    def _rand_cell(self) -> tuple[int, int]:
        rng = self.engine.rng
        return int(rng.integers(0, WORLD_CELLS)), int(rng.integers(0, WORLD_CELLS))

    # Genomas diferenciados por especie (fenotipos tras GeneticsSystem).
    # LEG_LENGTH dicta speed = leg*1.5; FUR_THICKNESS -> cold_resistance;
    # FUR_COLOR -> camouflage.
    SPECIES_GENOMES = {
        "neque":    {"fur_color": "brown", "fur_thickness": 4, "leg_length": 8},      # speed=12, camo=0.4
        "tigrillo": {"fur_color": "brown", "fur_thickness": 5, "leg_length": 14},     # speed=21 — caza por velocidad
        "aguila":   {"fur_color": "brown", "fur_thickness": 3, "leg_length": 10},     # speed=15 — ignora camo de presa
        "pajarito": {"fur_color": "white", "fur_thickness": 2, "leg_length": 9},      # speed=13.5, camo=0.8 (se esconden)
        "feral":    {"fur_color": "brown", "fur_thickness": 4, "leg_length": 16},     # muy rápido (raza perro/gato)
        "cazador":  {"fur_color": "brown", "fur_thickness": 2, "leg_length": 20},     # humano, veloz y certero
    }

    def _spawn(self, species: str, n: int) -> None:
        for _ in range(n):
            x, y = self._rand_cell()
            if species == "neques":
                self.registry.create_entity(
                    Position(x=x, y=y),
                    SpeciesRef(species_id="neque"),
                    GenomeComponent(genes=dict(self.SPECIES_GENOMES["neque"])),
                    PhenotypeComponent(),
                    # 50 (no 100): no se reproduce inmediatamente al spawnear
                    # (el umbral de reproducción es 80).
                    EnergyComponent(current_energy=50, max_energy=100),
                    Diet(diet_type=DietType.HERBIVORE),
                )
            elif species == "tigrillos":
                self.registry.create_entity(
                    Position(x=x, y=y),
                    SpeciesRef(species_id="tigrillo"),
                    GenomeComponent(genes=dict(self.SPECIES_GENOMES["tigrillo"])),
                    PhenotypeComponent(),
                    EnergyComponent(current_energy=50, max_energy=150),
                    Diet(diet_type=DietType.CARNIVORE),
                )
            elif species == "aguilas":
                self.registry.create_entity(
                    Position(x=x, y=y),
                    SpeciesRef(species_id="aguila"),
                    GenomeComponent(genes=dict(self.SPECIES_GENOMES["aguila"])),
                    PhenotypeComponent(),
                    EnergyComponent(current_energy=50, max_energy=120),
                    Diet(diet_type=DietType.CARNIVORE),
                )
            elif species == "cazadores":
                # AHORA sí son entidades ECS: cazan ñeques y tigrillos con
                # éxito casi garantizado (su genoma les da speed alta).
                self.registry.create_entity(
                    Position(x=x, y=y),
                    SpeciesRef(species_id="cazador"),
                    GenomeComponent(genes=dict(self.SPECIES_GENOMES["cazador"])),
                    PhenotypeComponent(),
                    EnergyComponent(current_energy=60, max_energy=120),
                    Diet(diet_type=DietType.CARNIVORE),
                )
            elif species == "pajaritos":
                # Presa aérea REAL: la cazan tigrillos (salto) y águilas.
                # Genoma diferenciado → speed 13.5, camuflaje 0.8 (huyendo).
                self.registry.create_entity(
                    Position(x=x, y=y),
                    SpeciesRef(species_id="pajarito"),
                    GenomeComponent(genes=dict(self.SPECIES_GENOMES["pajarito"])),
                    PhenotypeComponent(camouflage=0.6, speed=10.0),
                    EnergyComponent(current_energy=50, max_energy=80),
                    Diet(diet_type=DietType.HERBIVORE),
                )

    def _remove(self, species: str, qty: int) -> int:
        victims = [e for e in self._entities_of(species)][:qty]
        for e in victims:
            self.registry.destroy_entity(e)
        return len(victims)

    def _entities_of(self, species: str) -> list:
        out = []
        for entity, pos in self.registry.query(Position):
            if self._species_of(entity) == species:
                out.append(entity)
        return out

    def _species_of(self, entity) -> str | None:
        """Mapea entity -> clave de tarjeta. Las especies de fondo NO aparecen."""
        sref = self.registry.get_component(entity, SpeciesRef)
        if sref is not None and sref.species_id:
            if sref.species_id in BACKGROUND_SPECIES:
                return None        # fondo: viven pero no se muestran en UI
            return {
                "neque": "neques", "tigrillo": "tigrillos",
                "aguila": "aguilas", "pajarito": "pajaritos",
                "feral": "feral",
                "cazador": "cazadores",
            }.get(sref.species_id)
        return None

    # -- snapshot -------------------------------------------------------------

    def _biomass_grid(self, out_cells: int = 32) -> list[list[float]]:
        """Downsamplea el Field 'biomass' (128x128) a una matriz out_cells²
        (promedio por bloque), para que el cliente dibuje el fondo sin tener
        que bajar 16k floats por tick."""
        import numpy as np

        world = self.engine._world
        full = np.zeros((WORLD_CELLS, WORLD_CELLS), dtype=np.float64)
        for iy in range(world.height_chunks):
            for ix in range(world.width_chunks):
                chunk = world.chunk(ChunkCoord(ix, iy))
                bio = chunk.field("biomass").interior
                y0, x0 = iy * world.chunk_size, ix * world.chunk_size
                full[y0:y0 + world.chunk_size, x0:x0 + world.chunk_size] = bio
        block = WORLD_CELLS // out_cells
        small = full.reshape(out_cells, block, out_cells, block).mean(axis=(1, 3))
        return np.round(small, 1).tolist()



SIM = Simulation()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silencia el log por-request
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    #: Tamaño máximo aceptado de un body JSON (evita agotamiento de RAM).
    MAX_JSON_BYTES: int = 1 * 1024 * 1024  # 1 MB

    def _read_json(self) -> dict:
        raw = self.headers.get("Content-Length")
        if not raw:
            return {}
        length = int(raw)
        if length < 0:
            raise ValueError("Content-Length negativo")
        # Límite duro: rechazar payload gigante sin leerlo del socket.
        if length > self.MAX_JSON_BYTES:
            raise ValueError(f"payload JSON excede {self.MAX_JSON_BYTES} bytes")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self._send_json(SIM.snapshot())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            data = self._read_json()
            if self.path == "/api/tick":
                self._send_json(SIM.tick())
            elif self.path == "/api/population":
                self._send_json(
                    SIM.modify_population(
                        data.get("species", "neques"),
                        data.get("action", "add"),
                        data.get("qty", 1),
                    )
                )
            elif self.path == "/api/climate":
                self._send_json(SIM.set_climate(data.get("mode", "lluvia")))
            elif self.path == "/api/env":
                self._send_json(SIM.set_env(data))
            elif self.path == "/api/species_env":
                self._send_json(
                    SIM.set_species_env(data.get("species", "neque"), data.get("values", {}))
                )
            elif self.path == "/api/reset":
                self._send_json(SIM.reset())
            elif self.path == "/api/human_pressure":
                # Palancas directas 0..1 desde la UI (cada slider del panel).
                with SIM._lock:
                    hp = SIM.human_pressure
                    for key in ("active", "urbanization", "food_scarcity",
                                "contamination", "hunters", "noise", "roads",
                                "invasive"):
                        if key in data:
                            setattr(hp, key, float(data[key]) if key != "active" else bool(data[key]))
                self._send_json(SIM.snapshot())
            else:
                self._send_json({"error": "not found"}, 404)
        except Exception as exc:  # nunca caerse por un request malo
            traceback.print_exc()                      # traza real en consola
            self._send_json({"error": str(exc)}, 500)


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[web] Engine + UI en http://localhost:{port} (Ctrl+C para salir)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
