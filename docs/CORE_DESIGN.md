# Core Design — Population Engine

> Scope: a **technical design / roadmap** for the simulation *core* (the
> permanent, always-on loop that keeps a population alive across long,
> deterministic runs) and the seam that connects it to the engine, world, and
> the future plugin layer. This is a design document, not an implementation:
> everything below describes *what* to build and *how the parts relate*. No
> module here is code; it is a contract the upcoming phases will fill in.
>
> Status context. Subsystems already landed and tested: `core/` (engine
> lifecycle, `EngineConfig`, `Clock`/`TimePoint`/`SeasonCalendar`),
> `ecs/` (archetype `Registry`, `Entity`, `Event`/`EventBus`, `System`/
> `SystemContext`/`Scheduler`), and `world/` v1 (bounded chunk grid,
> ghost-padded `Field`s, spatial entity index). The next milestone is the
> simulation core itself. This document defines it before any system code is
> written.

---

## 1. Guiding principles

1. **Mathematical-first.** Every behavioural family — energy balance, metabolism,
   reproduction, foraging, movement, mortality, selection — is expressed as a
   *pure equation* over a typed state view: `f(state, params, exposure, dt, rng)
   → deltas`. There is no per-species logic and no ad-hoc rule table. The legacy
   principle "behaviour emerges from parameters" carries over unchanged; only the
   container changes (fat OOP `Animal` class → thin mutable ECS components +
   immutable data templates + pure models).

2. **Three-layer separation of concerns.**
   - **`data/`** — immutable, authored *templates* (species parameters, biome
     definitions, resource types, disease definitions). Pure data + loaders. No
     behaviour, no ECS, no world.
   - **`models/`** — pure *equations*. Pure functions over plain views; the
     science. No ECS, no world, no data loaders. Independently unit-testable
     with hand-built state vectors. This layer is the literal home of
     "mathematical-first."
   - **`systems/`** — ECS *integrators*. Thin glue: iterate the matching
     components, fetch the relevant template/exposure, call the model, write the
     delta back onto the component, publish notifications. All math lives in
     `models/`; a system contains no equation of its own.

3. **One fixed source of truth per kind of state.**
   - Per-individual mutable state → **ECS components** (integrated each tick).
   - Shared spatial/grid state → **world `Field`s** (SoA grids, many-reader).
   - Authored constants → **`data/` templates** (loaded once, frozen, by-id lookups).
   No overlap: a value is in exactly one of these places.

4. **Notifications vs. commands are different channels.** The existing
   `EventBus` (queue-backed, exact-type, FIFO `flush`) is for *notifications* —
   what *happened* (birth, death, consumption, predation). Structural changes to
   the entity set (spawn / despawn) are *commands*, handled by a dedicated
   engine-owned commit phase, never by arbitrary event handlers. Keeping these
   apart is what makes the scheduler's parallel stages safe: **during
   `Scheduler.execute` no archetype edge transitions happen**, only in-place
   component mutation; entity creation/destruction is deferred to the commit.

5. **World is an opt-in dependency, not a fixture.** The whole entity pipeline
   is engineered so that most systems never import `world.*`. A system may touch
   the world only if it reads/writes spatial `Field`s or the per-cell entity
   index; everything else stays spatially blind and unit-testable without chunks
   or halos.

6. **Determinism is a hard contract.** One shared `ctx.rng` (the engine's seeded
   `Generator`) consumed in a fixed system order; components mutated in place in
   archetype order. Same seed + same systems + same input → bit-identical runs.

---

## 2. The engine tick — composition and the seam

Today `Engine._advance_one` does `clock.advance(1)` then bumps `ticks_executed`.
The simulation-core seam extends one tick to a fixed six-phase composition. None
of the systems own this — the **engine** owns it:

```
Engine.tick  (state == RUNNING)
  1. clock.advance(1)                 # already exists
  2. world.refresh_halos()             # idempotent; makes all Fields stencil-ready
  3. Scheduler.execute(ctx)            # the simulation step (parallel-safe stages)
  4. EventBus.flush()                  # deliver this tick's notifications (FIFO)
  5. structural_commit()               # apply queued spawn / despawn requests
  6. emit(evt) → next-tick observers   # census snapshot, etc.
```

- **Phase 2 (`refresh_halos`)** runs once, after the Field-writing systems of the
  *previous* tick and before any system stencils a neighborhood this tick. It is
  idempotent w.r.t. interiors (only halo rings are recomputed), so running it
  unconditionally is correct and cheap.
- **Phase 3** is the only place simulation behaviour happens, and it only mutates
  existing components in place. No `create_entity` / `destroy_entity` /
  `add_component` during a stage — that is the structural-commit's job.
- **Phase 5** drains the structural queue in a fixed sub-order: despawns first
  (dead entities vacate archetype rows), then spawns (new entities appended).
  Flush handlers that *want* to create entities publish on the structural queue,
  not on the event bus.

### `SystemContext` — the single seam

`SystemContext` is already a frozen `(registry, events)`; its docstring promises
extension with clock + RNG. The core closes that seam:

```
SystemContext  (frozen)
  registry   : Registry            # existing
  events     : EventBus            # existing
  clock      : Clock               # NEW — read .now() for season/time-of-day
  rng        : np.random.Generator # NEW — the engine's shared deterministic stream
  world      : World              # NEW — only used by spatially-aware systems
  data       : DataRegistry        # NEW — frozen template lookup (data/ , see §7)
```

Adding all four fields atomically (in the engine-integration phase S0, §9) means
no system ever needs a constructor argument for shared state — systems stay
zero-arg, scheduler-friendly objects, matched to the existing `System` shape.

---

## 3. Core systems vs. optional plugins

The **permanent core** is the irreducible closed loop: the set of systems without
which a population cannot both sustain and turnover across an unbounded run. The
**plugin layer** is additive: features that are real but not required for
closure, registered into the engine at startup (components + systems + models +
events).

### 3.1 Permanent core systems (always on)

| # | System | Role | Writes | Touches World? |
|---|--------|------|--------|---------------|
| 1 | `ClimateSystem` | Drive environmental `Field`s from biome + season + altitude + RNG noise. | climate `Field`s | **yes** (Field writer) |
| 2 | `ResourceSystem` | Regenerate vegetation biomass & cell water from climate + season. | resource `Field`s | **yes** (Field writer) |
| 3 | `ExposureSystem` | Snapshot each entity's local cell climate+biomass+water into a `CellExposure` component. | `CellExposure` | **yes** (reads Fields, writes component) |
| 4 | `AgingSystem` | Increment `Age`, recompute life-stage flag. | `Age` | no |
| 5 | `MetabolismSystem` | Integrate basal + activity energy, hunger, thirst, thermoregulation into `Vitals`. | `Vitals` | no |
| 6 | `MovementSystem` | Resolve directed/territorial/random walk; update `Position` + world entity index. | `Position`, `MovementLog`, world index | **yes** (index writer) |
| 7 | `ReproductionSystem` | Gestation progression, birth probability, litter creation; queue spawns. | `Reproductive` | no (Position is a component) |
| 8 | `ForagingSystem` | Herbivory (consume resource), carnivory (hunt prey), flee; reduce hunger/thirst. | `Vitals` | **yes** (reads prey index) |
| 9 | `MortalitySystem` | Death checks (hp, age, extremes); tag cause; queue despawns. | — (emits) | no |
| 10 | `CensusSystem` | Aggregate per-tick population snapshot for observable streaming. | — (emits) | **yes** (spatial aggregation) |

Ten core systems. Only five (`1,2,3,6,8,10` — Climate, Resource, Exposure,
Movement, Foraging, Census) touch the world; the remaining four (`4,5,7,9` —
Aging, Metabolism, Reproduction, Mortality) are **world-free** and therefore
fully unit-testable with synthetic components alone.

> Why `ExposureSystem` (system 3) exists at all: it is the *decoupling hinge*.
> Rather than every entity system calling `ctx.world.value("temperature", pos)`
> — which would couple the entire entity pipeline to chunk/halo internals — one
> system copies the entity's local cell climate+biomass+water into a per-entity
> `CellExposure` component each tick. Downstream systems (Metabolism,
> Reproduction, Foraging-herbivory, Mortality) read the component, never the
> `Field` object. The cost is one snapshot per entity per tick; the win is that
> the whole entity physics pipeline is world-agnostic (§8).

### 3.2 Optional plugins (additive, registered via the host)

These do not belong to the closed loop. Each is a self-contained bundle of
(component + model + system + events) plugged in at startup. The README already
lists the plugin category; the design pins the membership.

| Plugin | Adds | Core dependency it extends |
|--------|------|------------------------------|
| `DiseasePlugin` | `Infection`/`Immunity` components, `DiseaseModel` (SIR-style), `DiseaseSystem`, transmission/recovery events | Metabolism (severity → hp/energy), Mortality (disease cause) |
| `GeneticsPlugin` | `Genome`/allele components, `InheritanceModel`, `MutationModel`, `GeneticsSystem` (on birth) | Reproduction (spawn carries genome) |
| `SelectionPlugin` | `FitnessModel`, fitness-weighted survival, `SelectionSystem` | Mortality (non-uniform death) |
| `FirePlugin` | disturbance `Field`, fire-spread model, `FireSystem` | Resource (burns biomass), Climate |
| `HumanActivityPlugin` | deforestation / poaching / presence factors, `HumanActivitySystem` | Mortality (poaching), Resource (deforestation) |
| `MigrationPlugin` | long-range movement beyond territory | Movement |
| `NecrologyPlugin` | carcass → nutrients `Field`/component | Resource, Foraging (scavengers) |
| `SocialPlugin` | flock/herd/pack components, social models | Movement, Foraging (cooperative hunt) |
| `AnalyticsPlugin` | rich statistics beyond the core census | Census |

**Reconciling the README:** the README's "mathematical-first" line names disease
and selection as core *equations*, while its "plugin host" line names disease and
genetics as *plugins*. Both are right once we separate the layers: the **model**
(e.g. `DiseaseModel`) lives in the core math library `models/` — reusable and
unit-tested in isolation — but the **system + component** that activates it
(`DiseaseSystem` + `Infection`) is a plugin that is *not* in the permanent loop.
The science is core; whether it runs is a plugin choice.

---

## 4. System dependency graph and tick staging

Dependencies are declared two ways, matching the existing `Scheduler`:
- **`reads`/`writes`** component sets → the scheduler auto-places conflicting
  systems (shared component with a writer) in different stages (read/read is *not*
  a conflict, so co-readers may share a stage).
- **`after`** explicit names → for dependencies the component model cannot see,
  notably the **world entity index** and the **`Field`/halo read-after-write**
  boundary (the index and halos are not ECS components, so the scheduler's
  conflict detection does not cover them — these dependencies must be expressed
  with `after`).

### Tick stages (conflict-free; intra-stage systems are parallel-safe)

```
Stage 1  ClimateSystem                       writes climate Fields
Stage 2  ResourceSystem      [after 1]       writes resource Fields
         ExposureSystem      [after 1,2]     writes CellExposure component
Stage 3  AgingSystem         ‖               writes Age
         MovementSystem     [after 2; idx]   writes Position, MovementLog, world index
Stage 4  MetabolismSystem   [after 3]        writes Vitals
Stage 5  ReproductionSystem [after 3,4]      writes Reproductive, queues spawns
         (parallel with nothing writing its inputs)
Stage 6  ForagingSystem     [after 3,5; idx] writes Vitals, queues despawns (prey)
Stage 7  MortalitySystem   [after 6]         queues despawns (deaths)
Stage 8  CensusSystem       [after 7]        emits snapshot (read-only)
```

Justification of the staging by component write-sets (the scheduler computes this
from declarations; shown here to make the contract explicit):

- `Vitals` has a single writer *per stage*: Metabolism (stage 4) then Foraging
  (stage 6). Reproduction reads `Vitals` but writes only `Reproductive`, so it
  sits in its own stage (5) between them — it consumes post-metabolism vitals and
  must not race Foraging's `Vitals` write.
- `Position` is written only by Movement (stage 3); Foraging reads it (prey
  lookup) in stage 6 — expressed both by `Vitals` ordering and by
  `ForagingSystem after MovementSystem` for the world-index dependency.
- Climate/Resource `Field`s are written in stages 1–2; every Field *reader*
  (Exposure in stage 3, Movement in stage 3, Census in 8) comes after, and the
  engine's `refresh_halos` (tick phase 2) guarantees neighborhood reads are
  stencil-correct.

### Why `after` is required even with `reads`/`writes`

The world per-cell entity index (and halos) is *not* an ECS component, so:
- `ForagingSystem after MovementSystem` — Foraging's prey query (`world.entities_at`) must see this tick's positions.
- `MortalitySystem after ForagingSystem` — deaths can depend on predation outcomes.
- Every Field-reader declares `after` the Field-writer of the same `Field`, *and* relies on the engine running `refresh_halos` before stage 3.

This is stated as a **standing rule**: *any system that reads the spatial index
or a neighborhood `Field` must declare `after` every system that writes
positions / that `Field`.*

---

## 5. ECS component set and per-system access

### 5.1 Core components (the schema of an animal entity)

Mapped from the legacy `Animal` ~30 instance vars + ~30 species class params,
split per the ownership rule in §1.3: mutable per-instance → component; immutable
per-species → template in `data/`; a few per-instance-but-derived → component
defaulting from the template.

| Component | Fields | Originates from legacy | Notes |
|-----------|--------|------------------------|-------|
| `SpeciesRef` | `species_id: str` | `species_name` | Pointer into the `data/` template registry. The ~30 species params are looked up via it, never stored per entity. |
| `Position` | `Coord` (world `CellCoord`) | `position_x/y` | Single source of truth for location; Movement is its only writer. |
| `Vitals` | `hunger, thirst, energy, hp: float` | `hp/hunger/thirst/energy` (were int 0–100) | Floats because they integrate an ODE each tick. Capped to `[0, max]` from the template. |
| `Age` | `age_ticks: int`, `stage: enum{JUVENILE,MATURE,SENESCENT}` | `age` | Stage recomputed from `age` vs template maturity/max-age thresholds. |
| `Reproductive` | `sex`, `gestation_ticks: int`, `mate_id: Entity\|None`, `parental_care_ticks: int` | `sex, gestation_timer, partner_id` | Gestation is a countdown; `0` ⇒ not gestating. |
| `Diet` | `diet_type: enum`, `consumes: tuple[str,...]` (resource + prey species ids) | `diet_type, diet_consumes, prey_species` | Defaults from template; a *component* (not template-only) to allow per-individual specialization / domestication later. |
| `MovementLog` | `distance_this_tick: float`, `state: enum{FORAGE,FLEE,MIGRATE,REST,...}` | `current_state, memory` | `state` is **derived** (argmax of weighted needs), not a hand-coded FSM — see §10. |
| `CellExposure` | `temperature, humidity, biomass, water: float`, `biome_id: int` | (new — the decoupling hinge, §3.1) | Snapshotted per-entity each tick by `ExposureSystem`; the entity pipeline reads this, never `Field`s. |

### 5.2 Per-system component access (reads / writes)

| System | reads | writes | emits / queues |
|--------|-------|--------|-----------------|
| `ClimateSystem` | `Clock.now()` (season, day), altitude `Field`, `BiomeDef` (data), `rng` | climate `Field`s (temp/humidity/precip) | — |
| `ResourceSystem` | climate `Field`s, `ResourceType` defs (data), season | resource `Field`s (biomass/water) | — |
| `ExposureSystem` | `Position`, climate+resource `Field`s | `CellExposure` | — |
| `AgingSystem` | `Age`, `SpeciesRef`→maturity/max-age | `Age` | — |
| `MetabolismSystem` | `Vitals`, `CellExposure`, `Age`, `MovementLog`, `SpeciesRef`→metabolic_rate/tolerances | `Vitals` | — |
| `MovementSystem` | `Position`, `Vitals`, `MovementLog`, `CellExposure`, `SpeciesRef`→speed/vision/territory/aquatic/fly, neighborhood `Field`s | `Position`, `MovementLog`, world index | `MovementEvent` |
| `ReproductionSystem` | `Reproductive`, `Vitals`, `Age`, `Position`, `SpeciesRef`→repro_rate/gestation/litter/season/monogamy, season | `Reproductive` | `BirthEvent`; spawn request (offspring `Entity`+components) |
| `ForagingSystem` | `Position`, `Diet`, `Vitals`, `CellExposure`, `SpeciesRef`→hunt/strength/stealth, `world.entities_at` (prey), resource `Field`s (herbivory biomass) | `Vitals` | `ConsumptionEvent`, `PredationEvent`; despawn request (killed prey) |
| `MortalitySystem` | `Vitals`, `Age`, `CellExposure`, `SpeciesRef`→max_age/tolerances | — (mortality scratch/flag) | `DeathEvent{cause}`; despawn request |
| `CensusSystem` | `SpeciesRef`, `Position`, `Vitals`, `Age` | — | `PopulationSnapshotEvent` |

Templates are reached through `ctx.data` (a `DataRegistry`, §7) keyed by
`SpeciesRef.species_id`; systems never store species parameters on the entity.

---

## 6. Data ownership: `data/` vs ECS vs world

The three-way ownership rule (§1.3) in concrete terms:

### `data/` — immutable authored templates (frozen value objects + loaders)
- **`SpeciesTemplate`** — the entire legacy species "class parameter" set:
  `max_hp, max_energy, max_hunger, max_thirst, max_age, metabolic_rate,
  base_energy_cost, speed, flight_speed, swim_speed, vision_range,
  hunt_skill, escape_skill, stealth, strength, reproduction_rate,
  gestation_time, litter_size, mating_season_start/end, monogamous,
  parental_care_duration, min_reproduction_age, temperature_tolerance_min/max,
  humidity_tolerance_min/max, water_needs, disease_resistance,
  infant_survival_rate, territory_size`, and the *defaults* for `Diet`.
- **`BiomeDef`** — `carrying_capacity`, base climate, supported resource types,
  regen modifiers (replaces legacy `biomes.json` + `Environment.biomes_data`).
- **`ResourceType`** — `max_biomass, regeneration_rate, nutritional_value,
  toxicity, season_effect` (replaces legacy resource defs).
- **`DiseaseDef`** — `transmission_rate, severity, recovery, vectors` (replaces
  legacy `diseases.json`; `predators.json` folds into `Diet.consumes` /
  `prey_species`).
- Optional **climate scenario / forcing** data.

`data/` exposes a `DataRegistry`: a frozen, by-id lookup (`species(id) -> SpeciesTemplate`,
etc.) injected onto `SystemContext` as `ctx.data`. The directory ships JSON (or
embedded) sources + loaders; nothing here imports `ecs` or `world`.

### ECS — mutable per-instance integrating state
`Vitals, Age, Position, Reproductive, Diet, MovementLog, CellExposure`, plus
plugin-added state (`Genome`, `Infection`, …). These are the integration
variables the models differentiate each tick.

### world — shared spatial/grid `Field`s
The four canonical `FIELD_SCHEMA` fields (`altitude, temperature, humidity,
biome_id`) plus core-added resource grids (`vegetation_biomass`, `water`,
`precipitation`). These are **never** ECS components — they are dense shared
spatial state read by many systems and written by a few. Altitude is static
(generation-only); the climate/resource grids are dynamic; `biome_id` is a
**cached projection** (§10).

### The line in one sentence
> *Per-individual* state is an ECS component; *shared spatial* state is a world
> `Field`; *authored constants* are a `data/` template. A value's ownership is
> decided by who needs to read it and how often it changes — and it lives in
> exactly one of the three.

---

## 7. The `data/` layer interface

`data/` is the first thing systems need (every system reads templates), so it
lands before any system (§9). Its public surface is deliberately tiny:

- Frozen value objects: `SpeciesTemplate`, `BiomeDef`, `ResourceType`,
  `DiseaseDef` (frozen dataclasses; one per entity kind; ids are stable strings).
- `DataRegistry` — the lookup; constructed once from shipped sources; exposed as
  `ctx.data`. `species(id)`, `biome(id)`, `resource(type)`, `disease(id)`.
- Loaders — read the bundled sources (JSON/embedded) into the registry; validate
  once at load (missing fields, range checks); fail closed with a clear error.

Design invariants for this layer:
- No `ecs` import, no `world` import, no RNG, no time. Pure data + validation.
- Immutable after construction; a `DataRegistry` is never mutated at runtime.
- Tests construct a `DataRegistry` from inline dicts — no file I/O required to
  unit-test a system that consumes templates. This directly enables the
  world-free, registry-free testing of the math layer.

---

## 8. World decoupling — what may never touch the world

### Hard rule (never imports `world.*`)
- **`models/`** — every equation. Inputs are *plain views* (frozen dataclasses or
  numpy arrays), outputs are *deltas*. A model signature is e.g.
  `metabolism(vitals, params, exposure, dt, rng) -> VitalsDelta`. There is no
  `Field`, no `Chunk`, no `Registry` symbol in a model module. This is the
  mathematical-first guarantee: each equation is provable in isolation.
- **`data/`** — pure data + loaders (§7).
- **`ecs/`** — already world-free by construction (registry/scheduler/events
  import nothing from `world`); must stay so.
- **`core/`** — already world-free (`engine.py` imports neither `ecs` nor
  `world`); must stay so. The engine *holds* a world and a scheduler but does not
  reach into world internals.

### Soft rule (design pattern, enforced by review)
The entity pipeline must read spatial state only through the per-entity
`CellExposure` component (written once by `ExposureSystem`), never through
`ctx.world.field(...)`. Consequences:
- **World-coupled systems** (may import/use `world`): `ClimateSystem`,
  `ResourceSystem`, `ExposureSystem`, `MovementSystem` (writes the index),
  `ForagingSystem` (reads the prey index), `CensusSystem` (spatial aggregation).
- **World-free systems** (must not): `AgingSystem`, `MetabolismSystem`,
  `ReproductionSystem`, `MortalitySystem`, and every non-spatial plugin
  (`GeneticsPlugin`, `SelectionPlugin`, `DiseasePlugin`'s intra-entity effect).

The one genuinely unavoidable spatial coupling in the entity pipeline is
**carnivory's prey lookup** (`world.entities_at`). It is mitigated by keeping the
contract narrow: a system depends only on `World.entities_at` / `move_entity` /
`value` — three methods — never on `Chunk` or `Field` internals. The halo/halos
machinery stays invisible behind `refresh_halos`, which the engine owns.

This split is the reason the four world-free core systems and the entire `models/`
layer can be unit-tested with a hand-built `Vitals`/`Age`/`CellExposure` and no
chunks at all.

---

## 9. Recommended implementation order

Subsystems are landed, tested, and reviewed one at a time, per the project's
existing roadmap convention (core → ecs → world → … → dashboards). **Already
done:** core, ecs, world v1. The remaining sequence, each phase gated on
green tests + review before the next:

- **S0 — Engine integration (the seam).** Extend `SystemContext` with
  `clock, rng, world, data`; compose `Engine.tick` into the six-phase tick (§2);
  add the structural-commit queue. *No simulation behaviour yet*: a no-op system
  is enough to prove the seam and determinism. Gate: an end-to-end "tick N times,
  RNG stream is reproducible" test.
- **S1 — Data layer.** `data/` value objects + `DataRegistry` + loaders + tests
  (§7). No ECS/world. Gate: load bundled sources, by-id lookups work, validation
  fails closed.
- **S2 — Core components.** Define `SpeciesRef, Position, Vitals, Age,
  Reproductive, Diet, MovementLog, CellExposure` as `@dataclass(Component)` (§5).
  No behaviour. Gate: archetype layout + query tests.
- **S3 — Core systems, bottom-up (one at a time, each = system + its `models/`
  equation + tests):**
  1. `ClimateSystem` + `ClimateModel` (seasonal + altitudinal lapse + RNG noise; writes `Field`s; determinism + halo test).
  2. `ResourceSystem` + `ResourceModel` (logistic regrowth from climate).
  3. `AgingSystem` (trivial — first real ECS system; validates the seam cleanly).
  4. `ExposureSystem` (the decoupling hinge — proves the CellExposure pattern).
  5. `MetabolismSystem` + `EnergyModel` (basal + activity + thermoreg).
  6. `MovementSystem` + `MovementModel` (directed/territorial/random walk; stencil reads; world-index writes).
  7. `ReproductionSystem` + `ReproductionModel` (gestation, birth probability, spawn request — exercises the structural queue).
  8. `ForagingSystem` + `ForagingModel` (herbivory + predation + flee).
  9. `MortalitySystem` (death checks, cause tagging, despawn request).
  10. `CensusSystem` (snapshot emission).
  Gate per system: model unit-tests (synthetic state, no ECS/world) **and**
  system integration tests (ECS + data, world only where required) green.
- **S4 — Plugin host.** `plugins/` registration API: register components,
  systems, models, events into the `Registry`/`Scheduler`/`EventBus` at startup.
  Gate: a trivial plugin adds a component + system and runs end-to-end.
- **S5 — First plugins (each a self-contained bundle):** Disease, Genetics,
  Selection, Fire, HumanActivity (order by value-to-effort; Disease first as it
  most exercises the event/structural-request seams).
- **S6 — Clients / dashboards** (out of engine scope; consume streamed snapshots).

The defining property of this order is dependency-satisfaction: S0 unblocks
systems, S1 unblocks param reads, S2 unblocks systems, and S3 bottoms-out so each
system's inputs already exist (Climate before Resource; Exposure before the
Metabolism-family; Reproduction before Foraging's spawn/despawn proofs;
Mortality last so all causes are visible).

---

## 10. Open decisions and flagged inconsistencies

These are surfaced for decision **before** they bite; none block writing the
design, but each affects code once S0+ begin.

1. **README ↔ v1 contradiction (wording).** README §"Chunked world" says chunks
   are "generated procedurally **on demand**, enabling a practically **infinite**
   map." The confirmed v1 decision is a **finite**, **up-front** bounded grid
   (`World` pre-builds all `width_chunks × height_chunks` chunks at construction;
   `loaded_chunks` is constant; `chunk()` never grows it). Recommendation:
   reword README to "a bounded grid of fixed-size chunks, all generated up front
   at construction; infinite/on-demand generation is deferred to a later phase."
   Document-only change; no engine code affected.

2. **`biome_id` as a `Field` vs "Fields are the sole source of truth."** `biome_id`
   is a deterministic function of `(altitude, temperature, humidity)` + the
   biome table (`World.classify_chunk`) — it is a *projection*, not independent
   state. It sits in `FIELD_SCHEMA` as a fast denormalized cache so cell
   classification is a lookup, not a recompute. Recommendation: keep it as a
   `Field`, but document it explicitly as a **cached projection recomputed when
   climate changes** (the `ExposureSystem` reads it; `ClimateSystem` may refresh
   it). This reconciles the denormalization with the single-source-of-truth rule
   by naming it a cache.

3. **Universal state machine → utility-weighted behaviour.** Legacy `Animal`
   has an explicit `current_state` FSM ("Buscar_Comida", "Cazar", "Dormir", …).
   Mathematical-first replaces it with a **derived** `MovementLog.state` =
   argmax over weighted needs (hunger, thirst, energy, predation proximity),
   not a hand-coded transition table. There is no `TransitionTable` artifact; the
   *weights* are species parameters in the template. Decision needed: confirm
   utility-maximization (with a small softmax temperature for nondeterminism) vs.
   a threshold-cascade. Utility-max is the proposed default.

4. **Structural-commit ordering and event timing.** Birth this tick vs next tick:
   the commit runs after `flush`, so a creature born this tick exists from next
   tick onward (no half-tick state). Death similarly takes effect at next-tick
   start. This is the existing `EventBus` semantics ("reactions take effect on
   the following tick") extended to entity lifecycle. Confirm this is the desired
   cadence (it keeps within-tick parallelism clean; the cost is one tick of lag
   on structural changes).

5. **`data/` storage format.** JSON files vs embedded Python literals vs a small
   bundled DB. JSON mirrors the legacy intent and keeps data non-code; embedded
   literals avoid I/O in tests. Recommendation: loaders abstract the source; ship
   JSON, build `DataRegistry` in tests from inline dicts — source format stays
   swappable.

---

## 11. Appendix — legacy `Animal` → core mapping

The whole legacy fat-class model collapses onto three layers under
mathematical-first:

| Legacy `Animal` | New home | Layer |
|-----------------|---------|-------|
| `id, partner_id` | `Entity` handle / `Reproductive.mate_id` | ecs |
| `position_x/y` | `Position.coord` | ecs |
| `hp, hunger, thirst, energy` | `Vitals` (floats) | ecs |
| `age` + stage | `Age` | ecs |
| `sex, gestation_timer, partner_id, parental_care` | `Reproductive` | ecs |
| `current_state, memory` | `MovementLog` | ecs |
| `diet_type, diet_consumes, prey_species` | `Diet` (defaults from template) | ecs |
| `infection_status` | `Infection` (**plugin**) | ecs (plugin) |
| `territory_center`, `species_name` | `Position` / `SpeciesRef` | ecs |
| ~30 species "class params" (`max_*`, `metabolic_rate`, `speed`, `vision_range`, tolerances, `gestation_time`, `litter_size`, `mating_season`, `monogamous`, `hunt_skill`, `stealth`, `strength`, `territory_size`, `disease_resistance`, `infant_survival_rate`, …) | `SpeciesTemplate` | `data/` |
| behaviour methods (`update_metabolism`, `move`, `seek_food`, `hunt`, `flee`, `reproduce`, `check_death`, …) | `models/` pure equations + `systems/` integrators | models/systems |
| `Cell` properties (`temperature, humidity, precipitation, biome_type, water_level, vegetation_biomass, carrying_capacity, animal_ids_present`) | world `Field`s + per-cell entity index (already exist) | world |
| `Weather`/`Environment.generate_map` | `ClimateSystem` + world generation | systems/world |
| `Resources.regenerate/consume` | `ResourceSystem` + `ForagingSystem` | systems |
| `Diseases` (appearance/spread/effects) | `DiseasePlugin` (`DiseaseModel` in `models/`) | plugin |
| `Simulation.run_tick` orchestration | `Engine.tick` six-phase + `Scheduler` | core |
| `get_statistics` | `CensusSystem` + analytics plugin | systems/plugin |

The collapse is the whole point: **one unified engine, behaviour from
parameters, expressed as equations** — the legacy vision, re-housed in the ECS +
chunked-world substrate that is already built.
