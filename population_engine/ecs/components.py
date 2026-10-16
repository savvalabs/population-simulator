"""Core ECS components — the schema of an animal entity (S2).

These are the foundational, **data-only** components that future simulation
systems (S3+) consume. Each is a plain mutable ``@dataclass(Component)``: fields
only, no methods, no behaviour. Systems read and mutate component instances in
place; all logic lives in systems + models, never here.

Layer contract (CORE_DESIGN §5–§8):

* **World-free.** This module imports nothing from ``world``. ``Position``
  stores plain ``(x, y)`` ints rather than ``world.CellCoord``; a
  spatially-aware system converts to a world coordinate at the boundary, on
  demand. This keeps the whole entity component schema decoupled from the
  chunk/halo substrate.
* **``Reproductive.mate_id``** may hold an
  :class:`~population_engine.ecs.entity.Entity` handle or ``None``.

**Defaults are construction placeholders, not valid runtime state.** Every
field has a default so components can be constructed with no arguments (the
project's ECS construction/testing convention). Sentinel defaults such as
``SpeciesRef.species_id == ""`` or ``CellExposure.biome_id == 0`` are *not*
real entity values — real spawn logic populates them from the species template
(:mod:`population_engine.data`) and the world. Treat an all-default component
as **uninitialized**.

The ``(str, Enum)`` value types used by some fields (:class:`AgeStage`,
:class:`DietType`, :class:`MovementState`, :class:`Sex`) live in
:mod:`population_engine.ecs.enums`; their string values mirror the ``data``
layer's authored labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .component import Component
from .entity import Entity
from .enums import AgeStage, DietType, MovementState, Sex

__all__ = [
    "SpeciesRef",
    "Position",
    "Vitals",
    "Age",
    "Reproductive",
    "Diet",
    "MovementLog",
    "CellExposure",
    "GenomeComponent",
    "PhenotypeComponent",
    "EnergyComponent",
]


@dataclass
class SpeciesRef(Component):
    """Pointer to the entity's species entry in the ``data`` template registry.

    ``species_id`` is the stable string looked up via ``ctx.data.species(id)``.
    The ~30 species parameters live in the template, never per entity.
    """

    # Placeholder: "" is not a valid species id; spawn sets it from the template.
    species_id: str = ""


@dataclass
class Position(Component):
    """Absolute integer cell coordinate of the entity.

    Plain ``(x, y)`` ints — intentionally **not** ``world.CellCoord`` — so the
    component schema stays world-free (CORE_DESIGN §8). ``MovementSystem`` is
    the only writer; a spatially-aware system converts to a world coordinate at
    the boundary.
    """

    # Placeholder (0, 0): construction default; spawn assigns a real coordinate.
    x: int = 0
    y: int = 0


@dataclass
class Vitals(Component):
    """Integrating vital levels (floats; an ODE integrates them each tick).

    Capped to ``[0, max]`` from the species template at runtime. All-zero
    defaults are an uninitialized placeholder, not a live animal.
    """

    # Placeholder zeros: spawn sets these from the template's max_* values.
    hunger: float = 0.0
    thirst: float = 0.0
    energy: float = 0.0
    hp: float = 0.0


@dataclass
class Age(Component):
    """Age in ticks and the derived life-cycle stage.

    The stage is recomputed from ``age_ticks`` versus the template's maturity /
    max-age thresholds by a future ``AgingSystem``.
    """

    # age_ticks 0 pairs with JUVENILE for a newborn; both are overwritten by
    # spawn / AgingSystem as needed.
    age_ticks: int = 0
    stage: AgeStage = AgeStage.JUVENILE


@dataclass
class Reproductive(Component):
    """Reproductive state.

    ``gestation_ticks`` is a countdown to birth; ``0`` means not gestating.
    ``mate_id`` is the partner handle (for monogamous species) or ``None``.
    ``parental_care_ticks`` is a countdown; ``0`` means not in parental care.
    """

    # sex is a placeholder: spawn assigns; the MALE default is not meaningful.
    sex: Sex = Sex.MALE
    gestation_ticks: int = 0
    mate_id: Entity | None = None
    parental_care_ticks: int = 0


@dataclass
class Diet(Component):
    """Per-individual diet.

    Defaults are overridden from the species template at spawn; the component
    (rather than the template alone) allows per-instance specialization later
    (CORE_DESIGN §5.1). ``consumes`` is an immutable tuple of resource and
    prey-species ids.
    """

    # diet_type is a placeholder: spawn overrides it from the template's
    # diet_type label.
    diet_type: DietType = DietType.HERBIVORE
    consumes: tuple[str, ...] = ()


@dataclass
class MovementLog(Component):
    """Per-tick movement bookkeeping.

    ``state`` is **derived** (argmax of weighted needs), not a hand-coded FSM
    (CORE_DESIGN §10.3).
    """

    distance_this_tick: float = 0.0
    state: MovementState = MovementState.REST


@dataclass
class CellExposure(Component):
    """Snapshot of the entity's local cell environment, copied once per tick by
    a future ``ExposureSystem`` (the decoupling hinge, CORE_DESIGN §3.1).

    Downstream systems read this component, never the world ``Field`` objects.
    All-default values (including ``biome_id == 0``) are an uninitialized
    placeholder; ``ExposureSystem`` fills it each tick.
    """

    temperature: float = 0.0
    humidity: float = 0.0
    precipitation: float = 0.0
    biomass: float = 0.0
    water: float = 0.0
    # Placeholder: 0 is not a valid biome id; ExposureSystem sets it each tick.
    biome_id: int = 0


@dataclass
class GenomeComponent(Component):
    """Heritable genetic payload (the ADN), decoupled from physical stats.

    ``GeneticsSystem`` expresses these genes into a :class:`PhenotypeComponent`
    each tick; mutations alter ``genes`` (at ``mutation_rate`` probability)
    without ever touching the phenotype directly, so the phenotype is always
    a *derived* projection of the genome.

    ``genes`` maps a gene name to its base value; it must use a
    ``default_factory`` (never a shared mutable class-level default).
    """

    genes: dict = field(
        default_factory=lambda: {
            "fur_color": "white",
            "fur_thickness": 5,
            "leg_length": 5,
        }
    )
    mutation_rate: float = 0.05


@dataclass
class PhenotypeComponent(Component):
    """Physical stats expressed from the genome by ``GeneticsSystem``.

    All-zero is a construction placeholder; this component carries no
    authority of its own — it is recomputed from :class:`GenomeComponent`
    every tick and must never be hand-edited by other systems.
    """

    camouflage: float = 0.0
    cold_resistance: float = 0.0
    speed: float = 0.0


@dataclass
class EnergyComponent(Component):
    """Energy budget for movement/metabolism bookkeeping.

    ``current_energy`` is clamped to ``[0, max_energy]`` by the consuming
    systems (never here — components hold no behaviour).
    """

    current_energy: int = 100
    max_energy: int = 100
    # Causa del último daño recibido (para logging de extinción). No es
    # parte de la física — es una etiqueta diagnóstica escrita por quien daña
    # y leída por DeathSystem al recolectar.
    last_damage_source: str = ""
