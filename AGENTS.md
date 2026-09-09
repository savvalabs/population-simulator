# AGENTS.md

Notes for OpenCode sessions working in this repo. Read alongside `README.md` and
`docs/CORE_DESIGN.md`; both carry load-bearing context not duplicated here.

## Two codebases, one engine

- `population_engine/` — the engine. Active, tested, the only thing under
  development. All commands below target it.
- `PopulationSimulator/` — a **legacy, design-only prototype**. The `.py` files
  under `PopulationSimulator/backend/engine/` are empty stubs; the `.md` files
  are Spanish-language OOP design notes it superseded. Do **not** edit it as if
  it were live code and do **not** import from it. Its data JSON
  (`backend/database/{species,biomes,predators}.json`) is the *intended source*
  the new `data/` layer loads from, but the loader lives in `population_engine/data/`.
- README's "Repository layout" mentions `clients/` and `docs/legacy/`; neither
  exists at that path today (`docs/legacy/` is just `docs/`; `PopulationSimulator/`
  plays the legacy role). Trust the filesystem, not that tree.

## Commands

```bash
py -m venv .venv
# Windows:  .venv\Scripts\activate
py -m pip install -e ".[dev]"        # editable install + dev extra (pytest, pytest-cov)
pytest                               # full suite
pytest tests/ecs/test_scheduler.py   # one file
pytest tests/ecs/test_scheduler.py::test_x -q   # one test
py -m tests.test_structure           # structural smoke test, no pytest needed
```

- `pyproject.toml` sets `pythonpath=["."]` and `testpaths=["tests"]`; tests import
  `population_engine` and `tests.*` as top-level packages. The editable install
  is required so `population_engine` resolves on the repo root.
- Engine runtime dep is only `numpy>=2.0`; `dev` extra adds test tooling. Python `>=3.11`.
- No lint/typecheck/codegen commands are configured — don't invent one. If asked,
  say none exists; do not silently add ruff/mypy configs.

## Layer purity — enforced by tests, not just convention

`tests/models/test_climate.py` asserts `models/` imports neither `world`, `ecs`,
`core`, nor `data` at runtime. The same split is the rule for the whole engine:

- `models/` — pure equations. No `ecs`/`world`/`core`/`data` imports. Inputs are
  plain arrays/dataclasses; unit-testable with synthetic state only.
- `data/` — frozen templates + `DataRegistry` + loaders. No `ecs`/`world`.
- `ecs/` — registry/scheduler/events. Imports nothing from `world`.
- `core/` — engine orchestrator. Imports `ecs` (for `SystemContext`) but never
  reaches into `world` internals; it *holds* a World/Scheduler/EventBus and calls
  their public methods from `Engine.tick` only.
- `systems/` — the only layer allowed to import `world` (and only the
  spatially-aware systems: Climate, Resource, Exposure, Movement, Foraging,
  Census). World-free systems (Aging, Metabolism, Reproduction, Mortality) must
  not.

Adding an import from a forbidden layer will break an existing test. When adding a
new `models/*` or `data/*` test, mirror the import-purity assertion.

## Architectural contracts (normative)

- **Determinism is a hard contract**: one shared `ctx.rng` (`np.random.Generator`),
  consumed in fixed system order; components mutated in place in archetype order.
  Same seed + same systems + same input → bit-identical runs. Don't introduce
  per-call seeding or reorder systems casually.
- **No structural changes during `Scheduler.execute`**: spawn/despawn are *queued*
  and applied by the engine's structural-commit phase (tick phase 5), after
  `EventBus.flush`. See ADR-004. A system never calls `create_entity`; it emits a
  spawn/despawn request.
- **Do not invent math for Open Design Decisions**: If `docs/open-questions/` (like
  `D1-biome-acquisition.md` or pending `D2-D5`) leaves an equation or bounds
  undefined (e.g., altitude lapse rate, RNG noise distribution), do not guess or
  implement it silently. You must propose options and wait for approval. Currently,
  `D1` uses an injected interim provider to avoid ADR-002 feedback loops.
- **`ExposureSystem` is the decoupling hinge**: it snapshots each entity's local
  cell climate/biomass/water into a `CellExposure` component once per tick; every
  downstream entity system reads `CellExposure`, never `world.field(...)`. Don't
  shortcut this — it is what keeps the entity pipeline world-free and unit-testable.
- **`after` is required for non-component deps**: any system reading the world
  entity index or a neighborhood `Field` must declare `after` the writer of
  positions / that `Field` (the scheduler can't infer these — indices and halos
  are not ECS components).

ADRs in `docs/adr/` are **immutable once Accepted**; overturning one requires a
new superseding ADR, never editing the accepted file.

## Implementation staging (where things are)

Subsystems land one at a time, gated on green tests + review, per
`docs/CORE_DESIGN.md` §9: core → ecs → world → (S0 engine seam) → (S1 data) →
(S2 components) → (S3 core systems, bottom-up) → (S4 plugin host) → (S5
plugins) → (S6 clients/clients).

Current state (from git log + tree): **core, ecs, world v1, S0 seam, S1 data,
S2 components** are done. In S3, only `ClimateSystem` + `ClimateModel` exist so
far. When adding a core system, follow the bottom-up order in §9 and the
per-system component access table in §5.2 — its inputs must already exist.

## Repo-specific gotchas

- `tests/ecs/_components.py` is a **shared sample-components fixture module** for
  ECS tests (`Position`, `Velocity`, `Health`, `Tag`), not production code. Don't
  import it into `population_engine/`; extend it when ECS tests need new sample
  components.
- `.gitignore` excludes `.claude/`, `.venv/`, `*.egg-info/`, `saves/`. The
  `population_engine.egg-info/` dir present locally is generated by the editable
  install — leave it ignored.
- Docs and code can disagree on wording (README vs. `docs/CORE_DESIGN.md` had a
  known contradiction, resolved by ADR-001). If a README claim and an ADR
  conflict, the ADR wins; flag it rather than silently "fixing" one side.
