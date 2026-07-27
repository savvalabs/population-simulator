# ADR-004 — Entity structural changes apply in a structural commit phase

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** —
- **Superseded by:** —
- **Discussion source:** `docs/CORE_DESIGN.md` §2, §10.4

## Context

The `Scheduler` groups systems into conflict-free stages (a stage is a batch of
systems that share no written component and may therefore execute concurrently).
That concurrency safety rests on a single invariant: **during `Scheduler.execute`,
the archetypes and the rows within them do not change.** `Registry` lifecycle
calls break that invariant — `create_entity` / `destroy_entity` append or remove
rows and shift the fill-row; `add_component` / `remove_component` are archetype
*edge transitions* that re-home an entity's component instances into a different
column set and move its row. Any of these executed mid-`execute` invalidates the
iteration state of every other system in the same stage (row indices, query
cursors, archetype membership) and renders parallel stages unsafe.

Systems undeniably need to do these things — births, deaths, prey killed by a
predator, an egg hatching, an individual acquiring immunity. If each system
performed them inline during `System.update`, the scheduler's parallel-stage
guarantee would be falsifiable by any system at will, and the
`Scheduler.stages()` capability already shipped in `ecs/` would be a fiction.

The existing `EventBus` already separates notification from reaction: events
published during a tick are queued and only dispatched at a `flush` at tick end,
so reactions take effect on the following tick. That established *current V1
semantics* for reactions. It is an event-bus property — **not** an architectural
mandate about entity lifecycle, and it must not be made one.

## Decision

Introduce a **structural commit phase** owned by the engine. Structural requests
(spawn, despawn, add-component, remove-component) are **not** performed inline by
systems during `Scheduler.execute`; they are queued, and the engine applies them
in a single phase — `structural_commit` — run **after `EventBus.flush`** and before
the next tick. Within the commit, **despawns run before spawns** (vacated rows free
the space that spawns re-fill, minimising row churn and fill-shifts).

The normative contract this ADR establishes is deliberately **narrow**:
**structural changes are deferred out of `Scheduler.execute` and applied in a
defined commit phase, so within-tick archetype mutation is impossible and the
scheduler's parallel stages remain safe.** The existence and role of the commit
phase — the discipline — is the architectural commitment.

**This ADR does not make the observed one-tick delay an architectural
requirement.** In V1 the commit runs once per tick after flush, so an entity
created or destroyed in tick T is visible to systems only from tick T+1. That is
*current* behaviour, consistent with the `EventBus` "reactions take effect on the
following tick" guarantee, and it is the acceptable V1 cost of safe parallelism.
It is explicitly **not** a permanent engine guarantee: should a future version
discover a safe way to reduce that latency without breaking the commit-phase
discipline — for example a commit sub-phase between stages that preserves stage
cursors, or epoch-style staging — the lag may shrink or vanish without revising
this ADR. The ADR commits to the *discipline*, not to the lag.

## Consequences

- **Positive:** the scheduler's parallel-stage guarantee holds by construction:
  no system can mutate archetypes mid-execute, so a future concurrent executor of
  a single stage is safe; `flush` handlers cannot accidentally create entities
  inside a stage; structural requests are batched once per tick (a few aggregated
  row-moves) rather than scattered mid-execution (many transitions); the phase
  mirrors the deferred-delivery semantics the `EventBus` already established.
- **Negative (V1, scoped — not a guarantee):** structural effects are visible one
  tick late — a predator credited in T banks the energy in T+1; a calf born in T
  does not forage in T; during the lag, a death-marked entity remains queryable by
  census and foraging for one tick. This is **current behaviour**, acceptable for
  V1, and revisable later.
- **Neutral:** the engine owns a structural-request queue and the commit routine;
  its sub-ordering (despawns-then-spawns) is an implementation detail chosen to
  minimise row churn and may be revised without architectural impact.

**Contract for consumers:** plugins and clients must treat structural effects as
taking effect at the next tick **in V1**. They may rely on that for V1 behaviour
reproduction, but must **not** hard-code an assumption that the lag is *necessarily
and permanently* exactly one tick where correctness depends on it. A future
lag-reduction preserves this ADR (it preserves the discipline); it is then that
revision's responsibility to update consumers.

The norm is reviewable: **a reviewer rejects any system that calls
`create_entity` / `destroy_entity` / `add_component` / `remove_component`
synchronously inside `System.update`**; structural intent must go through the
queued request surface. The queue itself is the engine's, not a system's.

## Alternatives considered

1. **Allow inline structural mutation during `execute` (lag = 0).** Rejected.
   Making the scheduler's invariant the responsibility of every system author —
   "never mutate archetypes such that another system's cursor is invalidated" —
   is a discipline that cannot be enforced and that breaks the moment one system
   is careless. The only way to make lag-0 *safe* is to abandon parallel stages
   (collapse the schedule to strictly sequential execution), discarding exactly
   the capability `Scheduler.stages()` exposes. The cost of lag-0 is the loss of
   safe parallelism.
2. **Per-stage minibatch commits between stages (partial lag reduction).**
   **Deferred, not rejected.** This is precisely the kind of safe lag-reduction
   the ADR explicitly permits: a commit sub-phase that runs between stages and
   preserves stage-boundary cursors would reduce lag for some effects without
   abandoning the discipline. It requires cursor invalidation / re-snapshot logic
   that does not yet exist in the scheduler, so it is V-later. Crucially, *doing it
   later does not amend this ADR*, because the ADR commits to the commit phase, not
   to the lag.
3. **Snapshot / replay the registry each stage for full isolation.** Rejected for
   V1. Prohibitive cost and complexity; it trades away the very parallelism
   benefit it seeks.

> *Reversibility:* the **discipline** — no archetype mutation during `execute`,
> applied in a commit phase — is the structural, hard-to-reverse part, because it
> is tied to the parallel-stage hypothesis the `Scheduler` is already built on;
> once systems are written assuming "I do not mutate archetypes in `update`, I
> queue instead", reverting to inline mutation means refunding the scheduler and
> rewriting systems. The **observed one-tick lag** is current V1 semantics and is
> explicitly **not** locked in: a future lag-reduction that preserves the
> discipline does not require revisiting this ADR.
