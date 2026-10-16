"""Interfaz gráfica del Simulador Ecológico (Minca) — motor ECS + control de tiempo.

Ventana de 1200x800 dividida en:
* Panel de Control (izquierda, 400 px, fondo oscuro): título, reloj real del
  Engine ("Semana: X | Generación: Y"), una fila de botones de velocidad
  [Pausa][x1][x5][x10] y los toggles de escenario (Caos 2026, Depredadores).
* Visor del Mundo (derecha, 800 px): entidades del ECS como puntos por
  arquetipo — verde plantas / marrón herbívoros / rojo depredadores.

Tiempo del Director: 1 generación = 52 ticks-semana.
  x1 -> 10 s/generación, x5 -> 2 s/generación, x10 -> 1 s/generación.
El bucle usa ``pygame.time.get_ticks()`` y llama a ``engine.tick()`` (que
puede ejecutar varios ticks seguidos para no acumular retraso) según el
intervalo de la velocidad activa. Pausa = 0 no llama a tick.

Ejecutable de forma autónoma: ``python main_ui.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from population_engine.core.engine import Engine
from population_engine.core.config import EngineConfig
from population_engine.ecs.components import (
    CellExposure,
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
from population_engine.systems.death import DeathSystem
from population_engine.systems.environment_exposure import ExposureSystem
from population_engine.systems.environment_pressure import EnvironmentPressureSystem
from population_engine.systems.genetics import GeneticsSystem
from population_engine.systems.human_pressure import HumanPressureSystem
from population_engine.systems.predators import ForagingSystem, PredatorSystem
from population_engine.systems.reproduction import ReproductionSystem
from population_engine.systems.resources import ResourceSystem
from population_engine.world.world import World

# -- Constantes de layout -----------------------------------------------------

WINDOW_WIDTH: int = 1200
WINDOW_HEIGHT: int = 800
PANEL_WIDTH: int = 400
VIEWPORT_WIDTH: int = WINDOW_WIDTH - PANEL_WIDTH  # 800

FPS: int = 60

# -- Tiempo -------------------------------------------------------------------
# 1 tick del Engine = 1 semana; 52 semanas = 1 generación.
WEEKS_PER_GENERATION: int = 52
# (velocidad, milisegundos por generación) según el Director:
#   x1 -> 10 s/gen, x5 -> 2 s/gen, x10 -> 1 s/gen.
SPEEDS: tuple[int, ...] = (0, 1, 5, 10)
_MS_PER_GENERATION: dict[int, int] = {1: 10_000, 5: 2_000, 10: 1_000}
_MS_PER_TICK: dict[int, float] = {
    speed: ms / WEEKS_PER_GENERATION
    for speed, ms in _MS_PER_GENERATION.items()
}

# -- Mundo ----------------------------------------------------------------------
# 4x4 chunks de 32 celdas -> 128 x 128 celdas.
WORLD_CHUNKS: int = 4
CHUNK_SIZE: int = 32
WORLD_CELLS: int = WORLD_CHUNKS * CHUNK_SIZE  # 128

# Poblaciones iniciales / eventuales
N_PLANTS: int = 40
N_HERBIVORES: int = 12
N_PREDATORS_ON_ACTIVATE: int = 4

# Temperatura base del "Modo Caos 2026" (ola de frío glacial).
NORMAL_BASE_TEMP: float = 20.0
CAOS_BASE_TEMP: float = -5.0

# Paleta
COLOR_PANEL_BG = (30, 32, 38)
COLOR_VIEWPORT_BG = (18, 22, 18)
COLOR_TEXT = (230, 230, 230)
COLOR_TEXT_DIM = (150, 150, 150)
COLOR_BTN_IDLE = (60, 64, 72)
COLOR_BTN_HOVER = (80, 86, 96)
COLOR_BTN_ON = (46, 139, 87)      # verde: activo
COLOR_BTN_ON_HOVER = (60, 160, 100)
COLOR_BTN_DANGER = (178, 60, 60)  # rojo: caos activo
COLOR_BTN_DANGER_HOVER = (200, 80, 80)
COLOR_BORDER = (90, 94, 102)

# Colores de entidades por arquetipo
COLOR_PLANT = (60, 180, 75)       # verde
COLOR_HERBIVORE = (150, 105, 60)  # marrón (ñeques)
COLOR_PREDATOR = (220, 50, 40)    # rojo

PANEL_RECT = pygame.Rect(0, 0, PANEL_WIDTH, WINDOW_HEIGHT)
VIEWPORT_RECT = pygame.Rect(PANEL_WIDTH, 0, VIEWPORT_WIDTH, WINDOW_HEIGHT)


# -- Estado de la UI ----------------------------------------------------------


@dataclass
class UIState:
    """Estado mutable de la interfaz (única fuente de verdad de los controles).

    ``time_speed``: 0 = Pausa, 1 = x1, 5 = x5, 10 = x10.
    """

    time_speed: int = 1
    modo_caos_2026: bool = False
    depredadores_activos: bool = False


# -- Widgets ------------------------------------------------------------------


@dataclass
class Button:
    """Botón rectangular dibujable con Pygame, con estados hover/activo.

    Para los botones de velocidad, ``toggled`` se usa como "es la velocidad
    activa"; no se auto-conmuta en clic — quien lo pulsa fija ``time_speed``.
    """

    rect: pygame.Rect
    label: str
    toggled: bool = False
    danger_when_on: bool = False  # True -> se pinta rojo al activarse

    def base_color(self) -> tuple[int, int, int]:
        if self.toggled:
            on = COLOR_BTN_DANGER if self.danger_when_on else COLOR_BTN_ON
            hover = (
                COLOR_BTN_DANGER_HOVER
                if self.danger_when_on
                else COLOR_BTN_ON_HOVER
            )
        else:
            on, hover = COLOR_BTN_IDLE, COLOR_BTN_HOVER
        return hover if self.is_hovered() else on

    def is_hovered(self) -> bool:
        return self.rect.collidepoint(pygame.mouse.get_pos())

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """Devuelve True si el clic cayó dentro del botón (y lo conmuta)."""
        if self.rect.collidepoint(pos):
            self.toggled = not self.toggled
            return True
        return False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        pygame.draw.rect(surface, self.base_color(), self.rect, border_radius=6)
        pygame.draw.rect(surface, COLOR_BORDER, self.rect, width=1, border_radius=6)
        text = font.render(self.label, True, COLOR_TEXT)
        surface.blit(text, text.get_rect(center=self.rect.center))


# -- Motor: construcción y población ------------------------------------------


def _build_engine() -> tuple[Engine, Registry, World, UniformBiomeProvider, HumanPressureSystem]:
    """Cablea Engine + Registry + Scheduler + EventBus + World (S0-S3)."""
    registry = Registry()
    events = EventBus()
    world = World(
        width_chunks=WORLD_CHUNKS, height_chunks=WORLD_CHUNKS,
        chunk_size=CHUNK_SIZE,
    )

    scheduler = Scheduler()
    biome_provider = UniformBiomeProvider(base_temperature=NORMAL_BASE_TEMP)
    human_pressure = HumanPressureSystem(world_size=WORLD_CELLS)
    from population_engine.systems.species_env import SpeciesEnvSystem
    species_env = SpeciesEnvSystem(world_size=WORLD_CELLS)
    human_pressure.hunters = 0.4
    human_pressure.noise = 0.2
    human_pressure.contamination = 0.1
    # Cadena completa: genética -> clima -> exposición -> recursos (biomasa)
    # -> forrajeo (los ñeques comen) -> depredadores -> presión ambiental
    # -> presión humana -> muerte/recolección.
    for system in (
        GeneticsSystem(),
        ClimateSystem(biome_provider=biome_provider),
        ExposureSystem(),
        ResourceSystem(
            deforestation_getter=human_pressure.deforestation_factor
        ),
        ForagingSystem(),
        PredatorSystem(),
        ReproductionSystem(
            population_block=human_pressure.reproduction_suppressed,
            space_getter=species_env.reproduction_factor,
        ),
        EnvironmentPressureSystem(),
        human_pressure,
        DeathSystem(),
    ):
        scheduler.add_system(system)
    scheduler.build()

    engine = Engine(
        EngineConfig(seed=7, ticks_per_day=1),  # 1 tick = 1 semana
        registry=registry,
        scheduler=scheduler,
        events=events,
        world=world,
    )
    engine.start()
    # Biomasa inicial: pradera moderada para arrancar la cadena trófica.
    from population_engine.world.coords import ChunkCoord
    for iy in range(world.height_chunks):
        for ix in range(world.width_chunks):
            world.chunk(ChunkCoord(ix, iy)).field("biomass").interior[...] = 50.0
    return engine, registry, world, biome_provider, human_pressure


def _spawn_initial_population(engine: Engine, registry: Registry) -> None:
    """Plantas y ñeques (herbívoros) iniciales, deterministas vía rng del motor."""
    rng = engine.rng
    for _ in range(N_PLANTS):
        x = int(rng.integers(0, WORLD_CELLS))
        y = int(rng.integers(0, WORLD_CELLS))
        registry.create_entity(Position(x=x, y=y))
    for _ in range(N_HERBIVORES):
        x = int(rng.integers(0, WORLD_CELLS))
        y = int(rng.integers(0, WORLD_CELLS))
        registry.create_entity(
            Position(x=x, y=y),
            SpeciesRef(species_id="neque"),
            GenomeComponent(),
            PhenotypeComponent(),
            EnergyComponent(),
            Diet(diet_type=DietType.HERBIVORE),
        )


def _spawn_predators(engine: Engine, registry: Registry) -> None:
    """Genera una camada de depredadores (carnívoros) al activar el toggle."""
    rng = engine.rng
    for _ in range(N_PREDATORS_ON_ACTIVATE):
        x = int(rng.integers(0, WORLD_CELLS))
        y = int(rng.integers(0, WORLD_CELLS))
        registry.create_entity(
            Position(x=x, y=y),
            SpeciesRef(species_id="tigrillo"),
            GenomeComponent(),
            PhenotypeComponent(),
            EnergyComponent(current_energy=150, max_energy=150),
            Diet(diet_type=DietType.CARNIVORE),
        )


# -- Construcción y dibujo de la UI -------------------------------------------

_SPEED_LABELS: dict[int, str] = {0: "Pausa", 1: "x1", 5: "x5", 10: "x10"}


def _build_layout() -> dict[str, object]:
    """Fila de 4 botones de velocidad (y=170..214) + toggles de escenario."""
    w_speed, h, gap = 84, 44, 8
    speed_buttons = {}
    x = 20
    for speed in SPEEDS:
        speed_buttons[speed] = Button(
            pygame.Rect(x, 170, w_speed, h), _SPEED_LABELS[speed]
        )
        x += w_speed + gap
    return {
        "speed": speed_buttons,
        "caos": Button(
            pygame.Rect(20, 260, PANEL_WIDTH - 40, h), "Modo Caos 2026",
            danger_when_on=True,
        ),
        "predadores": Button(
            pygame.Rect(20, 330, PANEL_WIDTH - 40, h), "Depredadores"
        ),
    }


def _draw_panel(
    screen: pygame.Surface,
    state: UIState,
    buttons: dict[str, object],
    engine: Engine,
    registry: Registry,
    font_title: pygame.font.Font,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
) -> None:
    pygame.draw.rect(screen, COLOR_PANEL_BG, PANEL_RECT)

    # Título
    screen.blit(
        font_title.render("Simulador Ecológico", True, COLOR_TEXT), (20, 24)
    )
    screen.blit(font.render("- Minca -", True, COLOR_TEXT_DIM), (20, 56))

    # Reloj REAL: ticks del Engine. 1 tick = 1 semana; 52 semanas = 1 generación.
    weeks = engine.ticks_executed
    generations = weeks // WEEKS_PER_GENERATION
    clock_text = f"Semana: {weeks} | Generación: {generations}"
    screen.blit(font.render(clock_text, True, COLOR_TEXT), (20, 110))

    # Botones de velocidad: el activo se ilumina.
    speed_buttons = buttons["speed"]
    for speed, button in speed_buttons.items():
        button.toggled = state.time_speed == speed
        button.draw(screen, font)

    # Toggles de escenario
    buttons["caos"].toggled = state.modo_caos_2026
    buttons["predadores"].toggled = state.depredadores_activos
    buttons["caos"].draw(screen, font)
    buttons["predadores"].draw(screen, font)

    # Estado textual de los toggles
    caos_txt = "ON" if state.modo_caos_2026 else "OFF"
    dep_txt = "ON" if state.depredadores_activos else "OFF"
    screen.blit(
        font_small.render(f"Caos: {caos_txt}", True, COLOR_TEXT_DIM), (20, 312)
    )
    screen.blit(
        font_small.render(f"Cacería: {dep_txt}", True, COLOR_TEXT_DIM),
        (20, 382),
    )

    # Conteo de entidades vivas
    screen.blit(
        font_small.render(f"Entidades vivas: {len(registry)}", True, COLOR_TEXT_DIM),
        (20, WINDOW_HEIGHT - 30),
    )


def _entity_color(registry: Registry, entity) -> tuple[int, int, int]:
    """Color por arquetipo: rojo carnívoro / marrón herbívoro / verde planta."""
    diet = registry.get_component(entity, Diet)
    if diet is not None and diet.diet_type is DietType.CARNIVORE:
        return COLOR_PREDATOR
    if registry.has_component(entity, GenomeComponent):
        return COLOR_HERBIVORE
    return COLOR_PLANT


def _draw_viewport(
    screen: pygame.Surface, registry: Registry, font_small: pygame.font.Font
) -> None:
    pygame.draw.rect(screen, COLOR_VIEWPORT_BG, VIEWPORT_RECT)
    pygame.draw.rect(screen, COLOR_BORDER, VIEWPORT_RECT, width=2)

    # Escala celda -> píxel dentro del visor (128 celdas -> 800 px).
    scale = VIEWPORT_WIDTH / WORLD_CELLS
    for entity, pos in registry.query(Position):
        px = int(PANEL_WIDTH + (pos.x + 0.5) * scale)
        py = int((pos.y + 0.5) * scale)
        if not VIEWPORT_RECT.collidepoint(px, py):
            continue
        color = _entity_color(registry, entity)
        pygame.draw.circle(screen, color, (px, py), max(2, int(scale * 0.4)))


# -- Bucle principal ----------------------------------------------------------


def _handle_click(pos: tuple[int, int], state: UIState, buttons, engine: Engine,
                  registry: Registry, biome_provider: UniformBiomeProvider,
                  human_pressure: HumanPressureSystem,
                  predators_spawned: list[bool]) -> None:
    # Botones de velocidad (no conmutan: fijan el valor activo).
    for speed, button in buttons["speed"].items():
        if button.rect.collidepoint(pos):
            state.time_speed = speed
            return
    if buttons["caos"].handle_click(pos):
        state.modo_caos_2026 = buttons["caos"].toggled
        # Ola de frío glacial: baja la temperatura base del clima.
        biome_provider.base_temperature = (
            CAOS_BASE_TEMP if state.modo_caos_2026 else NORMAL_BASE_TEMP
        )
    elif buttons["predadores"].handle_click(pos):
        state.depredadores_activos = buttons["predadores"].toggled
        # Activa la presión humana exógena (caza / ruido / contaminación).
        human_pressure.active = state.depredadores_activos
        if state.depredadores_activos and not predators_spawned[0]:
            _spawn_predators(engine, registry)
            predators_spawned[0] = True


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Simulador Ecológico - Minca")
    clock = pygame.time.Clock()

    font_title = pygame.font.SysFont("arial", 28, bold=True)
    font = pygame.font.SysFont("arial", 20)
    font_small = pygame.font.SysFont("arial", 16)

    state = UIState()
    buttons = _build_layout()

    # -- Motor real ---------------------------------------------------------
    engine, registry, world, biome_provider, human_pressure = _build_engine()
    _spawn_initial_population(engine, registry)
    predators_spawned = [False]

    # -- Temporizador de ticks ----------------------------------------------
    # ``last_tick_ms`` marca el instante del último engine.tick() ejecutado.
    last_tick_ms = pygame.time.get_ticks()

    while True:
        # --- Eventos ------------------------------------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                engine.stop()
                pygame.quit()
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                _handle_click(
                    event.pos, state, buttons, engine, registry,
                    biome_provider, human_pressure, predators_spawned,
                )
                # Al cambiar de velocidad no hay "deuda" de ticks pendiente.
                last_tick_ms = pygame.time.get_ticks()

        # --- Simulación ---------------------------------------------------
        if state.time_speed > 0:
            interval = _MS_PER_TICK[state.time_speed]
            now = pygame.time.get_ticks()
            # Ejecuta tantos ticks como intervalos completos hayan pasado,
            # para no acumular retraso a velocidades altas.
            while now - last_tick_ms >= interval:
                engine.tick()  # 1 tick = 1 semana
                last_tick_ms += interval

        # --- Dibujo -------------------------------------------------------
        _draw_panel(screen, state, buttons, engine, registry, font_title, font, font_small)
        _draw_viewport(screen, registry, font_small)

        pygame.display.flip()
        clock.tick(FPS)


if __name__ == "__main__":
    main()
