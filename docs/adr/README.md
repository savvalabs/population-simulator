# Architecture Decision Records

Normative record of the architectural decisions that constrain Population Engine.
Each ADR documents a decision, the *why* behind it (the problem it solves and the
principle it establishes), its consequences, and the alternatives that were
rejected. ADRs are dated and immutable once **Accepted**; a decision is overturned
or revised only by a *new* ADR that supersedes the old — never by editing an
accepted one.

An ADR here is not a historical note. Its **Decision** states a rule the engine
and reviewers must enforce; its **Consequences** name what that rule buys, what
it costs, and what a reviewer should reject. The **Decision** section of each
ADR is the normative contract.

See `docs/CORE_DESIGN.md` for the overall design that these decisions derive from.

## Index

| ADR | Decision | Status |
|-----|----------|--------|
| [ADR-001](ADR-001-finite-up-front-chunk-generation.md) | The chunked world is finite and generated up front at construction | Accepted |
| [ADR-002](ADR-002-biome-id-cached-projection.md) | `biome_id` is a cached projection of `(altitude, temperature, humidity)`, not independent state | Accepted |
| [ADR-003](ADR-003-utility-weighted-behaviour.md) | Animal behaviour is utility-weighted and derived from parameters — not a coded FSM | Accepted |
| [ADR-004](ADR-004-structural-commit-phase.md) | Entity structural changes apply in a post-flush structural commit phase | Accepted |

## Deliberately not recorded as ADRs

- **Data-layer storage format** (JSON bundles for production + inline dicts for
  tests, behind swappable `data/` loaders). This is an implementation decision of
  phase **S1**, recorded in the `data/` module rather than as an ADR. A low-level
  `ADR-005` will be written only if multiple data formats or backends later
  coexist, at which point the abstraction becomes an architectural commitment
  rather than a convenience.
