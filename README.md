# Population Engine

A headless, data-driven ecological population simulation engine for the
Sierra Nevada de Santa Marta. The behaviour of every organism emerges from a
small set of parameters (ECS components) processed by a single simulation
tick — there is no per-species logic. The engine is independent of any UI;
clients (web, desktop, scientific) are observers/controllers of an otherwise
long-running headless process.

## Architecture summary

- **Engine / client separation.** The engine runs headless and can execute
  unattended for unlimited time. Clients never mutate the world directly; they
  observe streamed state and issue high-level commands.
- **Archetype ECS.** Entities are opaque IDs; data lives in components stored in
  contiguous archetype arrays; systems declare component access (read/write) and
  are scheduled as a dependency graph for deterministic, parallel execution.
- **Event system.** Decoupled, queue-backed, tick-bounded publish/subscribe used
  by systems and plugins.
- **Chunked world.** The world is a bounded grid of fixed-size chunks, all
  generated up front at construction; v1 has no lazy or streaming generation.
  On-demand and effectively-infinite generation is a deferred, later-phase
  capability (see ADR-001).
- **Mathematical-first.** Population dynamics, energy balance, disease,
  reproduction and selection are expressed as models/equations, not ad-hoc rules.
- **Plugin host.** Climate, genetics, fire, disease, human activity, etc. are
  plugins that register components, systems, events, and equations.

## Repository layout

```
population_engine/
  core/      engine lifecycle, configuration, time/calendar
  ecs/       archetype storage, queries, scheduler, events
  world/     chunks, cells, procedural generation, spatial index
  systems/   ECS systems implementing simulation behaviour
  models/    pure equations (climate, genetic expression, ...)
  plugins/   dynamically registered features
  data/      bundled data: species templates, biomes, resources
web_server.py          REST bridge (Python stdlib only) serving the web client + JSON API
gemini-code-*.html     single-file web client (canvas viewer, control panel, dashboard)
main_ui.py             local Pygame client (same engine, desktop window)
PopulationSimulator/   legacy design-only prototype — do not import (see AGENTS.md)
tests/                 engine test suite
docs/                  CORE_DESIGN, ADRs, open questions
```

## Getting started

```bash
py -m venv .venv
# Windows:   .venv\Scripts\activate
py -m pip install -e ".[dev]"
pytest
```

> The engine itself only depends on `numpy`. The `dev` extra adds the test
> tooling. The structural smoke test also runs without pytest:
> `py -m tests.test_structure`.

## Web simulator — quick instructions

Run the demo (engine + web UI, stdlib only, no extra dependencies):

```bash
py -m venv .venv                  # once
.venv\Scripts\activate            # Windows
py -m pip install -e ".[dev]"     # once
.venv\Scripts\python.exe web_server.py
```

Then open **http://localhost:8000** (any device on the same network works).

Using the simulator:

1. **Add animals** — *Gestión de Población* → pick a species + quantity →
   **+ Agregar**. Set exact Mascotas/Cazadores counts in the *Presión
   Humana* number inputs.
2. **Run** — ▶ Iniciar (⏸ pauses, 🔄 resets everything to a clean world).
3. **Time** — *Semanas por segundo* slider (1–20), first control in the panel.
4. **Climate** — Normal (Sierra Nevada seasons) / Sequía / Lluvia / Caos.
5. **Per-species environment** — dropdown + sliders (comida, espacio,
   contaminación, enfermedades). Only the selected species is affected.
6. **Human pressure** — master toggle + 5 levers (1–10): urbanización,
   deforestación, contaminación, ruido/turismo, carreteras.
7. **Read the world** — hover any animal to highlight its chart line;
   species cards show live counts and extinction causes; the eco-log
   records events; ☀️/🌙 toggles the theme (dark "ecological lab" by
   default, light "papel de campo" as the alternative). The client is a
   single self-contained HTML file: all engine interaction goes through
   the JSON API below, and the canvas palette is centralized in a
   `THEME` object at the top of its script.

## Web API

The web client talks to the engine exclusively through this JSON API
(served by `web_server.py`, thread-safe via an `RLock` on the simulation):

| Endpoint            | Method | Body                          | Description                                    |
|---------------------|--------|-------------------------------|------------------------------------------------|
| `/api/state`        | GET    | —                             | Snapshot without advancing the clock           |
| `/api/tick`         | POST   | `{}`                          | Advance 1 week, return snapshot                |
| `/api/population`   | POST   | `{species, action, qty}`      | Add/remove individuals                         |
| `/api/population_set`| POST   | `{species, qty}`              | Set exact population (Mascotas/Cazadores)      |
| `/api/climate`      | POST   | `{mode}`                      | normal / sequia / lluvia / caos               |
| `/api/species_env`  | POST   | `{species, values}`           | Per-species environment sliders                |
| `/api/human_pressure`| POST  | `{lever: 0..1, active}`       | Human-pressure levers + master toggle          |
| `/api/reset`        | POST   | `{}`                          | Rebuild the engine from scratch                |

## Status

This engine is built subsystem by subsystem (engine core → ECS → world → … →
dashboards). Each subsystem is landed, tested, and reviewed before the next, per
the project's implementation roadmap.
