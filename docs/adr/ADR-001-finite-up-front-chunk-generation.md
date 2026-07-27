# ADR-001 — The chunked world is finite and generated up front at construction

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** —
- **Superseded by:** —
- **Discussion source:** `docs/CORE_DESIGN.md` §10.1

## Context

The README's "Chunked world" architecture bullet describes the world as *"a grid
of fixed-size chunks generated procedurally **on demand**, enabling a practically
**infinite** map."* That sentence describes lazy, on-demand generation and an
unbounded map.

The implementation in `population_engine/world/world.py` does not behave that way.
`World.__init__` runs the full `width_chunks × height_chunks` nested loop in the
constructor and stores every chunk in `self._grid`. `loaded_chunks` is the constant
`width_chunks * height_chunks` and never grows. `chunk()` performs only a bounds
check and returns from the pre-built grid. There is no lazy generation, no
eviction, and no streaming.

The discrepancy is not cosmetic. The test suite codifies the finite/up-front
contract as a guarantee, not an implementation detail: `test_chunks_pre_built_up_front`
asserts `loaded_chunks` equals the full grid and does **not** increase on access;
`test_move_entity_across_chunks` asserts *"bounded: no new chunks materialise."*
Documentation that promises behaviour the code will not exhibit misleads
contributors (one reading the README would believe on-demand generation is
"missing" and duplicate a deliberately-deferred feature) and contradicts the
tests during review.

## Decision

The README "Chunked world" bullet is rewritten to describe the v1 behaviour
truthfully: a **bounded** grid of fixed-size chunks, **all generated up front at
construction**. On-demand / streaming / effectively-infinite generation is named
in the same bullet, explicitly as a **deferred, later-phase capability** rather
than current behaviour.

The norm: **the README is a contract, not an aspiration.** It must describe
behaviour the code guarantees in the version it ships. A future direction is
recorded by naming the future, not by describing it in the present tense.

## Consequences

- **Positive:** the README and the test suite no longer contradict; onboarding
  reflects reality; "infinite / on-demand" stays visible as a roadmap item
  without being described as implemented.
- **Positive:** the deferred capability (streaming generation, eviction, an
  effectively unbounded map) is confined to the world layer's
  generation/eviction strategy. `World`'s public surface (`chunk`, `has_chunk`,
  `loaded_chunks`, `value`, the entity-index methods) is what every consumer —
  including the upcoming systems — depends on. A later streaming implementation
  that preserves that surface does not ripple into the ECS, the scheduler, or any
  system.
- **Negative:** the most aspirational selling-point line is removed from a
  prominent location. Mitigated by keeping the future direction in the same
  bullet, so the strategic intent is not lost — only its misrepresentation as
  current behaviour.
- **Neutral:** no engine code changes; no test changes.

## Alternatives considered

1. **Implement on-demand generation now to match the README.** Rejected. It
   contradicts the confirmed v1 decision ("Mundo finito basado en Chunks para la
   v1") and the user-approved finite-grid scope; on-demand/streaming generation
   is a substantial, deliberately-deferred feature, not a documentation fix, and
   pulling it forward now would revisit an architecture decision that ADR-001
   exists to *align with*, not to overturn.
2. **Leave both README and code as-is.** Rejected. The contradiction generates
   recurring review friction and misleads every new contributor.

> *Reversibility:* trivial. This is a wording change in a markdown file; the
> future streaming capability remains available as a later-phase world-layer
> change that does not touch the public `World` surface.
