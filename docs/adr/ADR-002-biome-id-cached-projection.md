# ADR-002 — `biome_id` is a cached projection, not independent state

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** —
- **Superseded by:** —
- **Discussion source:** `docs/CORE_DESIGN.md` §10.2

## Context

`FIELD_SCHEMA` contains `biome_id` (int64) alongside `altitude`, `temperature`,
and `humidity`. The engine's design rule (`CORE_DESIGN.md` §1.3) is that world
`Field`s are the **single source of truth** for shared spatial state. `biome_id`
strains that rule, because it carries no information that is not already present
elsewhere: it is a deterministic function of the other three fields plus the
biome definition table. `World._classify_array(altitude, temperature, humidity)`
produces it during generation, and `World.classify_chunk` reproduces the identical
projection — a consistency the suite already enforces via
`test_generated_biome_id_equals_classify_chunk`.

Two designs resolve the strain:

- Store `biome_id` as a `Field` — a denormalised cache recomputed when its inputs
  change — so cell classification is a single int lookup, and access stays
  uniform with the rest of the schema.
- Drop it from the schema and reclassify on every read.

Recomputing on every read is wasteful: every consumer would re-run the
per-biome inclusive-min/exclusive-max range scan with first-match-wins instead of
a single integer read, and it breaks the uniform vectorised `Field` accessor that
the rest of the engine relies on (`chunk.field("biome_id").interior`). Storing it
as a cache is cheap (one int64 per cell — less than the three float source fields
combined) and preserves the single accessor pattern.

The only risk of a cache is staleness: if a system writes `altitude`,
`temperature`, or `humidity` without refreshing `biome_id`, the cached projection
silently disagrees with its inputs and downstream systems read a wrong biome. The
resolution is to make the refresh an **explicit contract**, not a code mechanism
that auto-detects invalidation.

## Decision

`biome_id` stays in `FIELD_SCHEMA` as a `Field`, and is documented as a **cached
projection** of `(altitude, temperature, humidity)` over the biome definition
table. It is **not a second source of truth**; the source is the three
climate/terrain fields plus the biome table.

The norm this ADR establishes, made explicit per the approval: **any system
authorised to write `altitude`, `temperature`, or `humidity` must refresh the
`biome_id` projection before any other system may consume it.** The refresh is the
responsibility of the writer whose mutation invalidates the cache; it is not a
separate ambient system that recomputes defensively. In v1 the only authorised
writer of those inputs is `ClimateSystem` (altitude is static, generation-only),
so `ClimateSystem` refreshes `biome_id` in its own stage, *before* `ExposureSystem`
snapshots `biome_id` into per-entity `CellExposure`.Refreshing on the writer's
stage — not at every read — is itself part of the contract.

## Consequences

- **Positive:** O(1) biome lookup per cell instead of a re-scan; uniform,
  SIMD-friendly `Field` access; the existing
  `test_generated_biome_id_equals_classify_chunk`-style assertions already pin
  cache-vs-projection consistency and can be extended to *"post-`ClimateSystem`
  `biome_id` equals `classify_chunk` each tick"*.
- **Positive:** the refresh contract carries forward cleanly if the biome table
  becomes runtime-authorable data — the same obligation applies to the writer of
  the inputs, keyed against whatever the table holds at that tick.
- **Negative:** a stale-cache hazard exists. A future or plugin writer of the three
  source fields that forgets to refresh leaves a silently wrong `biome_id`.
  Mitigated by: the single writer in v1; the contract stated here; and a reviewer
  rule (below) that rejects a climate/terrain-writing system which does not
  refresh.
- **Neutral:** one int64 per cell of memory — negligible.

The contract is now normative. **A reviewer rejects any system that writes
`altitude`, `temperature`, or `humidity` without refreshing `biome_id`**, and the
system's `reads`/`writes` + stage placement must make that refresh visible (it
write `biome_id`).

## Alternatives considered

1. **Remove `biome_id` from `FIELD_SCHEMA`; reclassify on every read.** Rejected.
   Loses the O(1) lookup, breaks uniform vectorised `Field` access, pushes
   first-match logic into every consumer, and complicates the `ExposureSystem`
   decoupling hinge (it would have to read three fields + carry the biome table to
   classify, instead of reading one).
2. **A dedicated `BiomeClassificationSystem` that unconditionally recomputes the
   full grid each tick.** Rejected as the default. It recomputes the projection
   even on ticks where no input changed — pure overhead when there is a single
   writer that can refresh at its own stage. Acceptable as a *fallback* should a
   second, hard-to-coordinate writer appear later; but with one writer refreshing
   on its stage, the dedicated system is waste.
3. **Treat `biome_id` as independent state, decoupled from climate.** Rejected. It
   would cease to be a function of climate, contradicting `_classify_array`, the
   biome table's documented semantics, and the single-source-of-truth rule —
   creating exactly the second source of truth this ADR exists to forbid.

> *Reversibility:* moderate in the cheap direction. Keeping it as a cached `Field`
> with a refresh contract is the cheaper direction to sustain and extend. The
> opposite move — dropping it from the schema and recomputing on the fly — is an
> isolated refactor scoped to `Chunk`, `FIELD_SCHEMA`, `World._generate_chunk`,
> and ~5 tests; it does not propagate to ECS / data / models. The "Field-as-cache
> + refresh contract" direction is pinned now.
