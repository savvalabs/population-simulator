# D1 — Per-cell biome acquisition for `ClimateSystem` (UNRESOLVED)

- **Status:** Unresolved architectural decision (open question deferred out of S3)
- **Owner:** engine architecture
- **Discussion source:** `docs/CORE_DESIGN.md` §3.1, §5.2, §6, §10.2;
  `docs/adr/ADR-002-biome-id-cached-projection.md`
- **Affects:** `ClimateSystem` (S3.1), and any future system whose per-cell
  runtime input depends on the authored `BiomeData.base_*` climate values.

## The gap

`ClimateSystem` must drive the climate `Field`s "from biome + season + altitude
+ RNG noise" (CORE_DESIGN §3.1), and §5.2 names its reads as
`Clock.now()` (season, day), the **altitude `Field`**, **`BiomeDef` (data)**,
and `rng`, writing the climate `Field`s (temperature / humidity / precipitation).

`BiomeData` carries per-**biome** `base_temperature` / `base_humidity` /
`base_precipitation` (and min/max ranges). Because those are per-biome values,
driving climate from them requires a **per-cell selection of one `BiomeData`
for each cell**. CORE_DESIGN never specifies the altitude/position → `BiomeData`
acquisition. Concretely:

- §5.2 pairs the per-cell altitude `Field` with the per-biome `BiomeDef` as
  separate reads and gives no join from a cell's coordinate/altitude into a
  `BiomeDef` entry.
- §10.2 and ADR-002 define `biome_id` as a **downstream write** —
  `biome_id = World.classify_chunk(altitude, temperature, humidity)` refreshed
  by `ClimateSystem` *from* the climate it just wrote, and read downstream by
  `ExposureSystem`. Reading `biome_id` back as a climate *input* would close a
  `biome → climate → biome` feedback loop and contradict ADR-002; it is
  therefore **not** the acquisition mechanism.
- The relationship between the world-layer classifier (`World.classify_chunk`,
  producing the int `biome_id`) and the data-layer `BiomeDef` table is itself
  unspecified (whether they share a biome set; whether `classify` is built from
  `BiomeData` ranges).

Per-cell biome acquisition for the climate driver is therefore a genuine
architectural gap, not an implementation detail.

## Interim resolution in force for S3 (the gap is NOT solved here)

Per the S3 directive, the gap is left unresolved inside S3. Instead the climate
driver is built against an **injected biome-provider dependency**, so the
unresolved acquisition lives at one replaceable seam and the equation is never
coupled to it:

- **`ClimateModel`** (pure equation, `models/`) receives **already-resolved**
  per-cell `base_temperature`, `base_humidity`, `base_precipitation` as explicit
  arguments, alongside altitude, the season label, and the RNG. It is
  **completely unaware** of `World`, `DataRegistry`, biome ids, and any
  biome-lookup mechanism. A future D1 decision replaces the provider, not the
  model.
- **`ClimateSystem`** (integrator, `systems/`) holds **no biome-selection
  algorithm**. It obtains the resolved base values from an injected provider
  (the seam), passes them to `ClimateModel`, writes the climate `Field`
  interiors, and refreshes `biome_id` per ADR-002.
- **`DataRegistry` is not modified**, **no new `World` field is introduced for
  D1** (in particular no `terrain_biome_id`), and **no biome-lookup algorithm
  is invented.**

## Candidates evaluated (NOT chosen; recorded for the eventual decision)

1. **Inline altitude-band selection in `ClimateSystem`.** The system maps each
   cell's altitude into the `BiomeData` whose `[min_altitude, max_altitude]`
   band contains it (first-match in load order). Disadvantage: a second biome
   notion coexists with `biome_id`; the authored altitude ranges overlap
   (several biomes share a floor of 0), so altitude is a non-unique selector.
2. **Authored static `terrain_biome_id` `Field`** frozen at generation.
   Disadvantage: a new world field — foreclosed by "do not introduce new world
   fields" for the interim.
3. **Drop per-cell biome from the climate driver** — `BiomeDef` becomes a
   generation seed / downstream consumer only. Disadvantage: amends §3.1/§5.2
   (climate no longer "from biome"); discards authored per-biome base climates
   at runtime.
4. **Altitude→`BiomeData` resolver owned by `data/`.** Disadvantage: a
   range-band selection with overlap resolution is logic, contesting §1.2's
   "data = pure data + loaders, no behaviour."

## What the future decision must supply

- The altitude/coordinate → `BiomeData` mechanism (one of the above, a
  refinement, or a new one), and where it lives (`world/`, `data/`, a bootstrap
  adapter, or `core/`).
- Whether the world-layer `classify_chunk` classifier and the data-layer
  `BiomeData` table are unified — and the bootstrap wiring that builds the
  world classifier from `BiomeData` ranges, which `World` does not currently
  perform (it defaults to `biomes=[]`, so `biome_id == 0` everywhere).
- The provider contract that `ClimateSystem` consumes, so that resolving D1
  changes only that seam and leaves `ClimateModel` untouched.

## Constraints carried forward

`ClimateModel` must remain import-free of `world`, `ecs`, `core`, and the
`data` loaders; biome base values enter it only as explicit arguments.
`ClimateSystem` must not own the selection algorithm. No `terrain_biome_id`
field; no new world field for D1; no `DataRegistry` change; no invented lookup
algorithm.
