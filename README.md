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
- **Chunked world.** The world is a grid of fixed-size chunks generated
  procedurally on demand, enabling a practically infinite map.
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
  plugins/   dynamically registered features
  data/      bundled data: species templates, biomes, resources
clients/     standalone clients (web / PixiJS, desktop, scientific, ...)
tests/       engine test suite
docs/legacy/ earlier design notes (superseded by this codebase)
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

## Status

This engine is built subsystem by subsystem (engine core → ECS → world → … →
dashboards). Each subsystem is landed, tested, and reviewed before the next, per
the project's implementation roadmap.
