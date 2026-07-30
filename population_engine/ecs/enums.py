"""Simulation enumerations shared by the core ECS components.

The enums referenced by the core ECS components in
:mod:`population_engine.ecs.components`. Each is a ``(str, Enum)`` so its
*value* is a plain string. This is deliberate: the string values mirror the
free-form identifiers already authored in the :mod:`data` layer (most directly
``SpeciesData.diet_type``, whose bundled values are ``"herbivore"`` /
``"carnivore"`` / ``"omnivore"`` / ``"scavenger"``). Because an enum member
*is* its string value, a future system can compare a component's
``Diet.diet_type`` member directly against a stored template label without a
conversion step — and the ``data`` layer never has to import (or know about)
these enums. It stays pure data.

This module is pure value definitions only. It imports nothing from ``world``,
``data``, ``core``, or any ECS machinery, keeping the ECS layer world-free
(CORE_DESIGN §8).
"""

from __future__ import annotations

from enum import Enum

__all__ = ["AgeStage", "DietType", "MovementState", "Sex"]


class Sex(str, Enum):
    """Biological sex of an individual.

    Values are lowercase English strings. Sex is *not* stored in the ``data``
    layer (it is assigned at spawn); the lowercase-string form keeps it
    consistent with the data layer's label convention.
    """

    MALE = "male"
    FEMALE = "female"


class AgeStage(str, Enum):
    """Life-cycle stage of an individual, derived from ``Age.age_ticks`` versus
    the species template's maturity / max-age thresholds (CORE_DESIGN §5.1).

    The stage is recomputed by a future ``AgingSystem``; this enum only names
    the stages.
    """

    JUVENILE = "juvenile"
    MATURE = "mature"
    SENESCENT = "senescent"


class DietType(str, Enum):
    """How an individual feeds.

    The string values **match** the ``diet_type`` identifiers authored in the
    ``data`` layer's species sources (``"herbivore"``, ``"carnivore"``,
    ``"omnivore"``, ``"scavenger"``), so a ``Diet.diet_type`` member compares
    directly against a
    :class:`~population_engine.data.models.SpeciesData` template's label.
    """

    HERBIVORE = "herbivore"
    CARNIVORE = "carnivore"
    OMNIVORE = "omnivore"
    SCAVENGER = "scavenger"


class MovementState(str, Enum):
    """Derived behavioural state of an individual's current movement.

    Per CORE_DESIGN §5.1 / §10.3, ``state`` is **not** a hand-coded FSM
    transition table (as in the legacy ``Animal.current_state``). It is
    *derived* each tick as the argmax of weighted needs (hunger, thirst,
    energy, predation proximity). The set is intentionally open (`...` in the
    design); future systems may extend it.
    """

    FORAGE = "forage"
    FLEE = "flee"
    MIGRATE = "migrate"
    REST = "rest"
