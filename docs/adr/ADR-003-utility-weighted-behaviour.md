# ADR-003 — Behaviour is utility-weighted and derived from parameters, not a coded FSM

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** —
- **Superseded by:** —
- **Discussion source:** `docs/CORE_DESIGN.md` §3.1, §5.1, §10.3

## Context

The legacy design gives every `Animal` an explicit `current_state` field and a
hand-coded "universal state machine": well-known states ("Buscar_Comida", "Cazar",
"Huir", "Dormir", …) and a transition table that picks the next state from needs
and species parameters. This is the classic game-AI finite-state machine: it is
extended only by adding new states and the transitions between them, and it is
understood only by tracing the table.

That directly conflicts with the engine's stated goal — **mathematical-first**,
"behaviour emerges from parameters, not ad-hoc rules" — and with the README's
framing: "population dynamics, energy balance, disease, reproduction and
selection are expressed as models/equations, not ad-hoc rules." A coded transition
table is precisely such a rule. It also scales poorly: every new modality
(migration, schooling, scent-marking, Mate-seeking) requires new states, new
edges, and a larger FSM rather than new parameters.

For a simulator whose whole premise is that behaviour is parameter-driven, the
state should be *derived* by a function over the individual's state and exposure —
the same way energy and mortality are — not selected by an author's table.

## Decision

Replace the finite-state machine with **utility-weighted behavioural selection**.
`MovementLog.state` is computed each tick as

```
state = argmax_i  weight_i(vitals, exposure, params)
```

a pure function of the individual's `Vitals`, its local `CellExposure` (the
decoupling hinge), and its species parameters. The weights are per-species
parameters living in `SpeciesTemplate`; the `utility` model lives in `models/` and
is unit-testable with synthetic state, with no ECS, world, or data coupling.

"Nondeterminism" — so that two identical individuals in identical conditions need
not act identically — is introduced through a **softmax temperature** applied to
the utility vector, drawn from the shared `ctx.rng`, preserving bit-for-bit
reproducibility across runs with the same seed.

The norm: **there is no transition-table artefact in the engine.** Behavioural
modalities are added as new weight terms plus their parameters, never as new FSM
states or edges. "States" are an *output* — the argmax label the model emits —
never an *input* that drives a hand-coded graph.

Per the approval, the *tunables* that shape how the argmax is taken — **softmax
temperature, ε-greedy, momentum / hysteresis weighting against the previous
`MovementLog.state`, exploration noise** — are **configuration parameters of
`SpeciesTemplate`, not structural decisions of the engine.** Adding or adjusting a
tunable does not change the engine and does not require a new ADR; only abandoning
the utility-weighted mechanism itself (replacing argmax-of-utilities with something
that is no longer utility-weighted) would.

## Consequences

- **Positive:** a new modality is a new term in `utility` plus template
  parameters — the engine and its test surface do not grow per behaviour; the
  selection is a pure function testable with synthetic `Vitals` / `CellExposure`
  / params (world-free, registry-free), matching the `models/` discipline; argmax
  over O(5–8) weights is negligible cost; `rng`-driven softmax keeps the run
  bit-reproducible.
- **Negative (accepted):** raw argmax is memoryless and greedy; without momentum
  it can oscillate tick-to-tick between adjacent modalities (forage ↔ rest). This
  is *not* resolved by re-introducing a transition table; it is resolved by
  exposing **momentum** as a template parameter that carries a fraction of the
  previous state's weight into the current score — i.e. by a tunable, not by
  structure.
- **Negative (accepted):** an argmax of weighted needs cannot express hard priority
  overrides ("migrate regardless of thirst") without large prefactor weights. The
  engine accepts this — such overrides are authored as template parameters, never
  as engine special-cases; there is no `if species.is_migratory` in the engine.
- **Neutral:** softmax temperature and momentum become template fields to author
  and validate in the data layer.

The contract is normative. **A reviewer rejects any system that introduces a
hard-coded state-transition table in place of the utility model**, and rejects
engine code that branches per-species or per-state. Behavioural variance is
parameter-led.

## Alternatives considered

1. **Keep the legacy FSM ("universal state machine" + transition table).**
   Rejected. It contradicts mathematical-first, couples behaviour to code rather
   than parameters, scales quadratically with modalities, and forces a
   transition-table artefact into the engine — the exact "ad-hoc rule" the design
   forbids.
2. **Hard argmax with no nondeterminism.** Rejected as default. Identical
   individuals in identical conditions would act identically, producing gridlock
   and synchronised populations. The softmax temperature restores behavioural
   variance while staying reproducible via `rng`.
3. **Behaviour-tree / hierarchical-task-network selection.** Rejected for v1.
   Higher expressive power, but far more authoring and engine surface; the
   utility-weighted model is the simpler option that fits "emergence from
   parameters," and a BT could be added later as an alternative `models/`
   selection without touching ECS or world — so adopting utility-weighting now
   does not foreclose it.

> *Reversibility:* the **paradigm** — utility-weighted, not FSM — is the part
> that is hard to reverse, because reverting to a FSM means rewriting `models/`
> and every system that relies on `state` being derived rather than stored. The
> tunables (softmax temperature, momentum, ε-greedy) are per-template and freely
> adjustable. Pin the paradigm now; defer tunables to the template.
